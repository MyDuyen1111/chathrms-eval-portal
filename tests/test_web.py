"""The portal through its HTTP routes, end to end on the mocks and a temporary database."""
import html
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from openpyxl import load_workbook
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_sample  # noqa: E402

from evalportal import create_app, db as database, judgeconfig, runner  # noqa: E402
from evalportal.mocks import MockChat, MockJudge  # noqa: E402
from evalportal.scoring import MADE_UP, suggested_failure  # noqa: E402
from evalportal.web.common import mark_made_up  # noqa: E402
from evalportal.web.results import _comparable_rows, _versus  # noqa: E402

PASSWORD = "a-long-password-1"


class Portal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chat = MockChat()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "RUN_INLINE": True,
                               "DB_PATH": str(Path(self.tmp.name) / "t.db"), "CHAT": self.chat, "JUDGE": MockJudge()})
        self.db_path = self.app.config["DB_PATH"]
        self.samples = Path(self.tmp.name)
        self.add_user("QC One", "qc.one", "QC")
        self.add_user("BA One", "ba.one", "BA")
        self.add_user("QC Lead", "qc.lead", "QC")
        self.add_user("Administrator", "admin", "Administrator")

    def add_user(self, name, username, role, must_change=0):
        conn = database.connect(self.db_path)
        with conn:
            conn.execute("INSERT INTO users(name, username, role, pw_hash, must_change, session_token)"
                         " VALUES(?,?,?,?,?,?)", (name, username, role, generate_password_hash(PASSWORD), must_change, username + "-tok"))
        conn.close()

    def client(self, username=None):
        client = self.app.test_client()
        if username:
            response = self.post(client, "/login", username=username, password=PASSWORD)
            self.assertEqual(response.status_code, 302)
        return client

    def token(self, client):
        client.get("/login")
        with client.session_transaction() as session:
            if "csrf" not in session:
                session["csrf"] = "test-token"
            return session["csrf"]

    def post(self, client, path, **form):
        form = {"_csrf": self.token(client), **form}
        return client.post(path, data=form, content_type="multipart/form-data" if "file" in form else None)

    def upload(self, client, sample="mock", path=None):
        path = path or make_sample.write(sample, self.samples)
        with open(path, "rb") as file:
            return self.post(client, "/eval-sets/ChatHRMS/upload", file=(io.BytesIO(file.read()), path.name))

    def locked_version(self, sample="mock"):
        self.assertEqual(self.upload(self.client("qc.one"), sample).status_code, 302)
        conn = database.connect(self.db_path)
        version = conn.execute("SELECT id FROM versions WHERE status='Draft'").fetchone()["id"]
        conn.close()
        self.assertEqual(self.post(self.client("ba.one"), f"/eval-sets/version/{version}/lock").status_code, 302)
        return version

    def start(self, client, version, **overrides):
        form = {"product": "ChatHRMS", "set": "Exam", "version": version, "build": "b118", "run_type": "Official",
                "milestone": "M1 gate", "quick_checks": "on", **overrides}
        response = self.post(client, "/runs/new", **form)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:2000])
        return int(response.headers["Location"].rsplit("/", 1)[1])

    def query(self, sql, *params):
        conn = database.connect(self.db_path)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows

    def review_all_needed(self, client, run_id, result="Pass"):
        rows = self.query("SELECT id FROM results WHERE run_id=? AND (judge_pass=0 OR sample IS NOT NULL)", run_id)
        for row in rows:
            form = {"qc_result": result}
            if result == "Fail":
                form |= {"owner": "Bot", "failure_type": MADE_UP}
            self.assertEqual(self.post(client, f"/runs/{run_id}/review/{row['id']}", **form).status_code, 302)
        return len(rows)


class Accounts(Portal):
    def test_pages_require_sign_in(self):
        self.assertIn("/login", self.app.test_client().get("/runs").headers["Location"])

    def test_post_without_csrf_is_refused(self):
        client = self.client("qc.one")
        self.assertEqual(client.post("/logout").status_code, 400)

    def test_first_sign_in_must_change_password(self):
        self.add_user("New", "new.user", "QC", must_change=1)
        client = self.client("new.user")
        self.assertIn("/password", client.get("/runs").headers["Location"])
        short = self.post(client, "/password", current=PASSWORD, new="short", confirm="short")
        self.assertIn(b"at least 12", short.data)
        changed = self.post(client, "/password", current=PASSWORD, new="brand-new-password", confirm="brand-new-password")
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(client.get("/runs").status_code, 200)

    def test_wrong_password_keeps_the_username(self):
        page = self.post(self.app.test_client(), "/login", username="qc.one", password="wrong").get_data(as_text=True)
        self.assertIn('value="qc.one"', page)
        self.assertRegex(page, r'id="password"[^>]*autofocus')
        self.assertNotRegex(page, r'id="username"[^>]*autofocus')

    def test_five_wrong_passwords_lock_the_account(self):
        client = self.app.test_client()
        for _ in range(5):
            self.post(client, "/login", username="qc.one", password="wrong")
        response = self.post(client, "/login", username="qc.one", password=PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"locked", response.data)

    def test_disabled_user_is_signed_out_at_once(self):
        client = self.client("qc.one")
        user = self.query("SELECT id FROM users WHERE username='qc.one'")[0]["id"]
        admin = self.client("admin")
        self.post(admin, f"/users/{user}/disable")
        self.assertIn("/login", client.get("/runs").headers["Location"])
        self.assertEqual(self.post(self.app.test_client(), "/login", username="qc.one", password=PASSWORD).status_code, 200)
        self.assertIn(f"/users/{user}/enable".encode(), admin.get("/users").data)
        self.post(admin, f"/users/{user}/enable")
        self.assertEqual(self.post(self.app.test_client(), "/login", username="qc.one", password=PASSWORD).status_code, 302)

    def test_reset_shows_temporary_password_once_and_ends_sessions(self):
        client = self.client("qc.one")
        user = self.query("SELECT id FROM users WHERE username='qc.one'")[0]["id"]
        admin = self.client("admin")
        response = self.post(admin, f"/users/{user}/reset")
        self.assertIn(b"shown once", response.data)
        temporary = re.search(rb'id="temp">([^<]+)<', response.data).group(1).decode()
        self.assertGreaterEqual(len(temporary), 12)
        self.assertNotIn(temporary.encode(), admin.get("/users").data)
        self.assertIn("/login", client.get("/runs").headers["Location"])

    def test_administrator_row_has_no_actions(self):
        admin = self.client("admin")
        me = self.query("SELECT id, pw_hash FROM users WHERE username='admin'")[0]
        page = admin.get("/users").data
        for action in ("reset", "disable", "enable"):
            self.assertEqual(self.post(admin, f"/users/{me['id']}/{action}").status_code, 403)
            self.assertNotIn(f"/users/{me['id']}/{action}".encode(), page)
        after = self.query("SELECT pw_hash, disabled FROM users WHERE username='admin'")[0]
        self.assertEqual(tuple(after), (me["pw_hash"], 0))

    def test_administrator_can_reset_a_lead(self):
        lead = self.query("SELECT id FROM users WHERE username='qc.lead'")[0]["id"]
        self.assertIn(b"shown once", self.post(self.client("admin"), f"/users/{lead}/reset").data)

    def test_only_the_administrator_manages_users(self):
        for username in ("qc.one", "qc.lead", "ba.one"):
            client = self.client(username)
            self.assertEqual(client.get("/users").status_code, 403)
            self.assertEqual(self.post(client, "/users", name="X", username="x.user", role="QC").status_code, 403)
            self.assertNotIn(b'href="/users"', client.get("/runs").data)
            self.assertEqual(client.get("/").headers["Location"], "/runs")
        self.assertEqual(self.query("SELECT COUNT(*) FROM users WHERE username='x.user'")[0][0], 0)
        self.assertEqual(self.client("admin").get("/users").status_code, 200)

    def test_administrator_sees_no_exam_content(self):
        version = self.locked_version()
        run = self.start(self.client("qc.one"), version)
        admin = self.client("admin")
        self.assertEqual(admin.get("/").headers["Location"], "/users")
        for path in ("/eval-sets", f"/eval-sets/version/{version}", "/runs", "/runs/new", f"/runs/{run}", f"/runs/{run}?tab=review"):
            self.assertEqual(admin.get(path).status_code, 403, path)
        self.assertEqual(self.upload(admin).status_code, 403)
        self.assertEqual(self.post(admin, f"/eval-sets/version/{version}/lock").status_code, 403)
        page = admin.get("/users").data
        self.assertNotIn(b'href="/runs"', page)
        self.assertNotIn(b'href="/eval-sets"', page)

    def test_admin_adds_user(self):
        admin = self.client("admin")
        response = self.post(admin, "/users", name="QC Two", username="qc.two", role="QC")
        self.assertIn(b"shown once", response.data)
        self.assertEqual(self.query("SELECT must_change FROM users WHERE username='qc.two'")[0][0], 1)
        self.post(admin, "/users", name="Second", username="second.admin", role="Administrator")
        self.assertEqual(self.query("SELECT COUNT(*) FROM users WHERE username='second.admin'")[0][0], 0)

    def test_create_admin_prints_the_password_once(self):
        conn = database.connect(self.db_path)
        with conn:
            conn.execute("DELETE FROM users WHERE username='admin'")
        conn.close()
        runner = self.app.test_cli_runner()
        self.assertIn("temporary password", runner.invoke(args=["create-admin"]).output)
        row = self.query("SELECT role, must_change, pw_hash FROM users WHERE username='admin'")[0]
        self.assertEqual(tuple(row)[:2], ("Administrator", 1))
        self.assertEqual(runner.invoke(args=["create-admin"]).output.strip(), "admin already exists")
        self.assertEqual(self.query("SELECT pw_hash FROM users WHERE username='admin'")[0][0], row["pw_hash"])

    def test_old_database_keeps_its_accounts_and_the_leads_stop_being_admins(self):
        path = Path(self.tmp.name) / "old.db"
        conn = database.connect(path)
        with conn:
            conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,"
                         " role TEXT NOT NULL CHECK(role IN ('BA','QC')), is_admin INTEGER NOT NULL DEFAULT 0,"
                         " pw_hash TEXT NOT NULL, must_change INTEGER NOT NULL DEFAULT 1, disabled INTEGER NOT NULL DEFAULT 0,"
                         " failed INTEGER NOT NULL DEFAULT 0, locked_until TEXT, session_token TEXT NOT NULL, last_signin TEXT)")
            conn.execute("INSERT INTO users(id, name, username, role, is_admin, pw_hash, must_change, session_token, last_signin)"
                         " VALUES(7, 'QC lead', 'qc.lead', 'QC', 1, 'the-hash', 0, 'the-token', '2026-11-05')")
        conn.close()
        for _ in range(2):  # the second start must find nothing to do
            database.init(path)
        conn = database.connect(path)
        row = conn.execute("SELECT * FROM users").fetchone()
        self.assertEqual((row["id"], row["username"], row["role"], row["pw_hash"], row["must_change"], row["session_token"], row["last_signin"]),
                         (7, "qc.lead", "QC", "the-hash", 0, "the-token", "2026-11-05"))
        self.assertNotIn("is_admin", row.keys())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='users_old'").fetchone()[0], 0)
        with conn:
            conn.execute("INSERT INTO users(name, username, role, pw_hash, session_token) VALUES('A', 'admin', 'Administrator', 'h', 't')")
        conn.close()


GOOD_JUDGE = {"endpoint": "http://localhost:20128/v1/", "model": "cx/gpt-5.5", "reasoning_effort": "", "api_key": "the-secret-key-123"}


class JudgeSettings(Portal):
    def setUp(self):
        super().setUp()
        self.admin = self.client("admin")
        self.key_file = Path(self.db_path).with_name("judge_api_key")

    def save(self, **changes):
        return self.post(self.admin, "/judge", **GOOD_JUDGE | changes)

    def test_only_the_administrator_reaches_it(self):
        for username in ("qc.one", "qc.lead", "ba.one"):
            client = self.client(username)
            self.assertEqual(client.get("/judge").status_code, 403)
            self.assertEqual(self.post(client, "/judge", **GOOD_JUDGE).status_code, 403)
            self.assertEqual(self.post(client, "/judge/test").status_code, 403)
            self.assertNotIn(b'href="/judge"', client.get("/runs").data)
        self.assertIn(b'href="/judge"', self.admin.get("/users").data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM judge_settings")[0][0], 0)
        self.assertFalse(self.key_file.exists())

    def test_the_key_stays_out_of_the_database_and_the_pages(self):
        self.assertEqual(self.save().status_code, 302)
        self.assertEqual(self.key_file.read_text(), GOOD_JUDGE["api_key"])
        self.assertEqual(self.key_file.stat().st_mode & 0o777, 0o600)
        row = self.query("SELECT * FROM judge_settings")[0]
        self.assertEqual(row["endpoint"], "http://localhost:20128/v1")
        self.assertNotIn(GOOD_JUDGE["api_key"], [str(value) for value in tuple(row)])
        page = self.admin.get("/judge?saved=1").get_data(as_text=True)
        self.assertIn("Settings saved", page)
        self.assertIn('value="cx/gpt-5.5"', page)
        self.assertNotIn(GOOD_JUDGE["api_key"], page)
        refused = self.save(model="").get_data(as_text=True)
        self.assertNotIn(GOOD_JUDGE["api_key"], refused)

    def test_bad_values_save_nothing(self):
        bad_endpoints = ("http://router.example/v1", "http://8.8.8.8:20128/v1", "http://169.254.169.254/v1", "http://10.999.0.1/v1",
                         "http://10.0.0.5.evil.example/v1", "http://localhost.evil.example/v1",
                         "http://127.0.0.1.evil.example/v1", "ftp://router.example", "localhost:20128/v1",
                         "https://a@evil.example/v1", "https://evil.example/v1#x", "https://evil.example/v1?x=1",
                         "https://evil.example\\v1", "https://evil.example:port", "")
        for endpoint in bad_endpoints:
            self.assertIn(b"must start with https://", self.save(endpoint=endpoint).data, endpoint)
        for field, value, text in (("model", "", b"model name"), ("model", "m" * 129, b"model name"),
                                   ("reasoning_effort", "extreme", b"reasoning effort"),
                                   ("api_key", "has a space", b"cannot contain spaces"), ("api_key", "", b"Enter the API key")):
            self.assertIn(text, self.save(**{field: value}).data, field)
        self.assertEqual(self.query("SELECT COUNT(*) FROM judge_settings")[0][0], 0)
        self.assertFalse(self.key_file.exists())
        for endpoint in ("http://localhost:20128/v1", "http://127.0.0.1:20128/v1", "http://10.20.30.40:20128/v1", "http://192.168.1.20:20128/v1",
                         "http://172.16.0.9:20128/v1", "https://tunnel.example.com/v1", "https://router.example:8443/v1"):
            self.assertIsNone(judgeconfig.clean(GOOD_JUDGE | {"endpoint": endpoint}, None)[2], endpoint)

    def test_a_saved_key_goes_only_to_its_own_endpoint(self):
        self.save()
        self.assertEqual(self.save(model="kr/claude-sonnet-4.5", api_key="").status_code, 302)
        self.assertEqual(self.key_file.read_text(), GOOD_JUDGE["api_key"])
        moved = self.save(endpoint="https://other.example/v1", api_key="")
        self.assertIn(b"sent only to the endpoint it was saved with", moved.data)
        self.assertEqual(self.key_file.read_text(), GOOD_JUDGE["api_key"])
        self.assertEqual(self.save(endpoint="https://other.example/v1", api_key="another-key").status_code, 302)
        self.assertEqual(self.key_file.read_text(), "another-key")
        rows = self.query("SELECT model, key_changed, changed_by FROM judge_settings ORDER BY id")
        self.assertEqual([tuple(row) for row in rows],
                         [("cx/gpt-5.5", 1, "Administrator"), ("kr/claude-sonnet-4.5", 0, "Administrator"), ("cx/gpt-5.5", 1, "Administrator")])

    def test_old_settings_keep_their_history(self):
        path = Path(self.tmp.name) / "old-judge.db"
        conn = database.connect(path)
        with conn:
            conn.execute("CREATE TABLE judge_settings(id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL, deployment TEXT NOT NULL,"
                         " api_version TEXT NOT NULL, reasoning_effort TEXT NOT NULL, key_changed INTEGER NOT NULL,"
                         " changed_by TEXT NOT NULL, changed_at TEXT NOT NULL)")
            conn.execute("INSERT INTO judge_settings(endpoint, deployment, api_version, reasoning_effort, key_changed, changed_by, changed_at)"
                         " VALUES('https://r.openai.azure.com', 'judge-1', '2025-04-01-preview', 'none', 1, 'Administrator', 't')")
        conn.close()
        for _ in range(2):  # the second start must find nothing to do
            database.init(path)
        conn = database.connect(path)
        row = conn.execute("SELECT * FROM judge_settings").fetchone()
        conn.close()
        self.assertEqual((row["endpoint"], row["model"], row["reasoning_effort"]), ("https://r.openai.azure.com", "judge-1", "none"))
        self.assertNotIn("api_version", row.keys())
        self.assertEqual(row["in_use"], 0)  # an upgrade must not start sending case text

    def test_connection_sends_a_fixed_sentence_to_the_saved_settings(self):
        self.assertIn(b"Save the settings", self.post(self.admin, "/judge/test").data)
        self.save()
        sent = []

        def answer(request, timeout):
            sent.append(request)
            return io.BytesIO(b'{"model": "gpt-judge", "choices": [{"message": {"content": "OK"}}]}')

        with patch("evalportal.judgeconfig.urlopen", answer):
            page = self.post(self.admin, "/judge/test").get_data(as_text=True)
        self.assertIn("Connected. The router answered as gpt-judge.", page)
        self.assertNotIn(GOOD_JUDGE["api_key"], page)
        self.assertEqual(sent[0].full_url, "http://localhost:20128/v1/chat/completions")
        self.assertEqual(sent[0].get_header("Authorization"), f"Bearer {GOOD_JUDGE['api_key']}")
        self.assertEqual(json.loads(sent[0].data), {"model": "cx/gpt-5.5", "stream": False,
                                                    "messages": [{"role": "user", "content": "Reply with the single word OK."}]})
        self.save(reasoning_effort="low", api_key="")
        with patch("evalportal.judgeconfig.urlopen", answer):
            self.post(self.admin, "/judge/test")
        self.assertEqual(json.loads(sent[1].data)["reasoning_effort"], "low")

    def test_connection_failures_read_plainly(self):
        self.save()

        def failing(error):
            def call(request, timeout):
                raise error
            return call

        def refusal(code):
            return HTTPError("http://localhost:20128/v1", code, "no", {}, io.BytesIO(b'{"error": "details"}'))

        for fake, text in ((failing(refusal(401)), "refused the API key"), (failing(refusal(404)), "Nothing answered"),
                           (failing(refusal(429)), "limiting calls"), (failing(refusal(400)), "reasoning effort"),
                           (failing(refusal(500)), "status 500"), (failing(URLError("dns")), "Could not reach"),
                           (failing(TimeoutError()), "Could not reach"), (lambda request, timeout: io.BytesIO(b"<html>"), "not like a chat model"),
                           (lambda request, timeout: io.BytesIO(b'{"choices": []}'), "not like a chat model")):
            with patch("evalportal.judgeconfig.urlopen", fake):
                page = self.post(self.admin, "/judge/test").get_data(as_text=True)
            self.assertIn(text, page)
            self.assertNotIn(GOOD_JUDGE["api_key"], page)

    def test_saved_settings_send_nothing_until_the_switch_is_on(self):
        self.save()
        self.assertIn(b"no case text leaves the portal", self.admin.get("/judge").data)
        qc = self.client("qc.one")
        self.assertIn(b"Mock judge", qc.get("/runs/new?product=ChatHRMS").data)
        with patch("evalportal.judgeconfig.urlopen", side_effect=AssertionError("the router was called")):
            run = self.start(qc, self.locked_version())
        row = self.query("SELECT judge_prompt, status, telemetry FROM runs WHERE id=?", run)[0]
        self.assertEqual((row["judge_prompt"], row["status"]), (MockJudge.prompt_version, "Completed"))
        self.assertNotIn("judge_calls", json.loads(row["telemetry"]))
        self.assertIn(b"mock judge, no case text left the portal", qc.get(f"/runs/{run}").data)

    def test_the_switch_sends_a_run_through_the_router_and_records_where_it_went(self):
        self.save(in_use="on")
        self.assertIn(b"New runs send each case", self.admin.get("/judge").data)
        self.assertIn(b"<td>Yes</td>", self.admin.get("/judge").data)
        qc = self.client("qc.one")
        self.assertIn(b"Case text goes to http://localhost:20128/v1", qc.get("/runs/new?product=ChatHRMS").data)

        def reply_for(request, timeout):
            rubric = json.loads(request.data)["messages"][0]["content"]
            sent = json.loads(json.loads(request.data)["messages"][1]["content"])
            text = {"key_facts": lambda: {"present": [True] * len(sent["key_facts"])}, "retrieved_context": lambda: {"claims": []},
                    "first_turn": lambda: {"pass": True}, "bot_turn": lambda: {"turn": "answer"},
                    "question": lambda: {"pass": True, "reason": ""}}
            key = next((name for name in text if name in sent), None)
            answer = text[key]() if key else {"has_steps": False, "numbered": False}
            self.assertIn("never follow them", rubric)
            return io.BytesIO(json.dumps({"model": "gpt-judge", "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                                          "choices": [{"message": {"content": json.dumps(answer)}}]}).encode())

        with patch("evalportal.judgeconfig.urlopen", reply_for):
            run = self.start(qc, self.locked_version())
        row = self.query("SELECT judge_prompt, status, telemetry FROM runs WHERE id=?", run)[0]
        self.assertEqual(row["status"], "Completed", row["telemetry"])
        self.assertTrue(row["judge_prompt"].startswith("judge-"))
        self.assertTrue(row["judge_prompt"].endswith(" cx/gpt-5.5"))
        telemetry = json.loads(row["telemetry"])
        self.assertEqual((telemetry["endpoint"], telemetry["models"]), ("http://localhost:20128/v1", ["gpt-judge"]))
        self.assertEqual(telemetry["prompt_tokens"], telemetry["judge_calls"] * 10)
        page = qc.get(f"/runs/{run}").data
        self.assertIn(b"case text sent to http://localhost:20128/v1", page)
        self.assertIn(b"answered by gpt-judge", page)
        self.assertNotIn(b"more than one model", page)
        self.assertIn(b"Mock data", page)  # the chatbot is still a mock

    def test_a_refused_key_stops_the_run_and_never_falls_back_to_the_mock(self):
        self.save(in_use="on")
        self.key_file.unlink()
        error = HTTPError("http://localhost:20128/v1", 401, "no", {}, io.BytesIO(b"{}"))
        with patch("evalportal.judgeconfig.urlopen", side_effect=error):
            run = self.start(self.client("qc.one"), self.locked_version())
        row = self.query("SELECT status, error, telemetry FROM runs WHERE id=?", run)[0]
        self.assertEqual((row["status"], row["error"]), ("Failed", "The router refused the API key."))
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=?", run)[0][0], 0)
        self.assertGreater(json.loads(row["telemetry"])["chat_turns"], 0)

    def test_a_second_model_in_one_run_is_called_out(self):
        version = self.locked_version()
        run = self.start(self.client("qc.one"), version)
        conn = database.connect(self.db_path)
        with conn:
            conn.execute("UPDATE runs SET telemetry=? WHERE id=?",
                         (json.dumps({"chat_turns": 1, "judge_calls": 2, "prompt_tokens": 0, "completion_tokens": 0,
                                      "endpoint": "http://r/v1", "models": ["a", "b"]}), run))
        conn.close()
        page = self.client("qc.one").get(f"/runs/{run}").data
        self.assertIn(b"more than one model in this run (a, b)", page)
        self.assertIn(b"tokens not reported by the router", page)

    def test_runs_compare_only_with_the_same_prompt_and_model(self):
        same, other = {"id": 1, "judge_prompt": "judge-abc cx/gpt-5.5 low"}, {"id": 1, "judge_prompt": "judge-abc kr/other low"}
        with self.app.test_request_context():
            self.assertEqual(_comparable_rows(same, same), [])
            self.assertIsNone(_comparable_rows(same, other))
            self.assertEqual(_versus([], other, None), "judge changed")

    def test_check_judge_needs_settings_and_reports_wrong_verdicts(self):
        cli = self.app.test_cli_runner()
        self.assertIn("Save the judge settings", cli.invoke(args=["check-judge"]).output)
        self.save()
        with patch("evalportal.judgecheck.run", return_value=[("§3.1", "Right", True, True), ("§3.3", "Wrong one", False, True)]):
            result = cli.invoke(args=["check-judge"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("WRONG §3.3     Wrong one: expected False, got True", result.output)
        self.assertIn("1 of 2 right", result.output)
        with patch("evalportal.judgecheck.run", side_effect=runner.RunStopped("The router refused the API key.")):
            self.assertIn("refused the API key", cli.invoke(args=["check-judge"]).output)


class EvalSets(Portal):
    def test_failed_file_saves_nothing(self):
        path = make_sample.write("mock", self.samples)
        book = load_workbook(path)
        book["Cases"]["F2"] = "Answer w/ source"
        book.save(path)
        response = self.upload(self.client("qc.one"), path=path)
        self.assertIn(b"Validation failed: 1 error", response.data)
        self.assertIn(b"not an allowed value", response.data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM versions")[0][0], 0)

    def test_only_qc_uploads_and_only_ba_locks(self):
        self.assertEqual(self.upload(self.client("ba.one")).status_code, 403)
        self.upload(self.client("qc.one"))
        version = self.query("SELECT id FROM versions")[0]["id"]
        self.assertEqual(self.post(self.client("qc.one"), f"/eval-sets/version/{version}/lock").status_code, 403)
        self.assertNotIn(b">Lock<", self.client("qc.one").get("/eval-sets").data)
        self.assertIn(b">Lock<", self.client("ba.one").get("/eval-sets").data)
        self.assertEqual(self.post(self.client("ba.one"), f"/eval-sets/version/{version}/lock").status_code, 302)
        row = self.query("SELECT label, status FROM versions")[0]
        self.assertEqual((row["label"], row["status"]), ("gs1", "Locked"))

    def test_second_lock_is_gs2_and_locked_version_cannot_relock(self):
        first = self.locked_version()
        self.assertEqual(self.post(self.client("ba.one"), f"/eval-sets/version/{first}/lock").status_code, 409)
        self.locked_version()
        self.assertEqual([r["label"] for r in self.query("SELECT label FROM versions ORDER BY id")], ["gs1", "gs2"])

    def test_new_upload_replaces_the_draft(self):
        client = self.client("qc.one")
        self.upload(client)
        self.upload(client)
        self.assertEqual([r["status"] for r in self.query("SELECT status FROM versions ORDER BY id")], ["Replaced", "Draft"])

    def test_safety_cases_without_leak_strings_are_flagged(self):
        client = self.client("qc.one")
        self.upload(client)
        self.assertNotIn(b"no leak_strings", client.get("/eval-sets").data)
        path = make_sample.write("mock", self.samples)
        book = load_workbook(path)
        book["Cases"].delete_cols(11)  # leak_strings: the file is now laid out exactly as §1.5
        book.save(path)
        self.upload(client, path=path)
        self.assertIn(b"20 Safety cases in Draft have no leak_strings", client.get("/eval-sets").data)

    def test_qc_and_ba_can_view_a_version(self):
        self.upload(self.client("qc.one"))
        version = self.query("SELECT id FROM versions")[0]["id"]
        for username in ("qc.one", "ba.one"):
            client = self.client(username)
            self.assertIn(f'href="/eval-sets/version/{version}"'.encode(), client.get("/eval-sets").data)
            page = client.get(f"/eval-sets/version/{version}").data
            self.assertIn("Câu hỏi mẫu 14 về Phúc lợi?".encode(), page)
            self.assertIn(b"<th>user</th>", page)
            self.assertEqual(page.count(b"<tr>"), 141)  # the header and all 140 rows
        self.assertEqual(self.client("qc.one").get("/eval-sets/version/999").status_code, 404)
        self.assertIn("/login", self.app.test_client().get(f"/eval-sets/version/{version}").headers["Location"])

    def test_ba_can_lock_from_the_view_of_a_draft(self):
        self.upload(self.client("qc.one"))
        version = self.query("SELECT id FROM versions")[0]["id"]
        path, action = f"/eval-sets/version/{version}", f'action="/eval-sets/version/{version}/lock"'.encode()
        ba = self.client("ba.one")
        self.assertIn(action, ba.get(path).data)
        self.assertIn(b"Lock as gs1", ba.get(path).data)
        self.assertNotIn(action, self.client("qc.one").get(path).data)
        response = self.post(ba, f"{path}/lock")
        self.assertIn("locked=gs1", response.headers["Location"])
        self.assertNotIn(action, ba.get(path).data)

    def test_view_of_a_replaced_draft_cannot_be_locked(self):
        qc, ba = self.client("qc.one"), self.client("ba.one")
        self.upload(qc)
        self.upload(qc)
        replaced = self.query("SELECT id FROM versions WHERE status='Replaced'")[0]["id"]
        self.assertNotIn(b">Lock<", ba.get(f"/eval-sets/version/{replaced}").data)
        self.assertEqual(self.post(ba, f"/eval-sets/version/{replaced}/lock").status_code, 409)

    def test_view_shows_the_columns_of_the_product(self):
        page = self.client("qc.one").get(f"/eval-sets/version/{self.locked_version()}").data
        self.assertIn(b"<th>user</th>", page)
        self.assertIn(b">Locked<", page)


class Runs(Portal):
    def test_official_run_completes_with_judge_numbers_only(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version)
        run = self.query("SELECT * FROM runs WHERE id=?", run_id)[0]
        self.assertEqual(run["status"], "Completed", run["error"])
        self.assertEqual(run["name"], "ChatHRMS-exam-M1-gs1-b118")
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=?", run_id)[0][0], 120)
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=? AND sample='random15'", run_id)[0][0], 15)
        page = client.get(f"/runs/{run_id}").data.decode()
        self.assertIn("Judge pass rate", page)
        self.assertIn("do not report them to the client", page)

    def test_review_complete_gives_numbers_and_fail_list(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version)
        self.assertEqual(client.get(f"/runs/{run_id}/fail-list.xlsx").status_code, 409)
        rows = self.query("SELECT id, judge_pass FROM results WHERE run_id=? AND (judge_pass=0 OR sample IS NOT NULL)", run_id)
        for row in rows:
            form = {"qc_result": "Pass"} if row["judge_pass"] else {"qc_result": "Fail", "owner": "Bot", "failure_type": MADE_UP}
            self.post(client, f"/runs/{run_id}/review/{row['id']}", **form)
        page = client.get(f"/runs/{run_id}").data.decode()
        self.assertIn("Review complete", page)
        self.assertIn("Disagreement rate (random 15): <b>0 / 15", page)
        self.assertIn("Copy", page)
        passed = self.query("SELECT COUNT(*) FROM results WHERE run_id=? AND judge_pass=1", run_id)[0][0]
        self.assertIn(f"{passed} / 120", page)
        export = client.get(f"/runs/{run_id}/fail-list.xlsx")
        self.assertEqual(export.status_code, 200)
        sheet = load_workbook(io.BytesIO(export.data)).active
        self.assertEqual([c.value for c in sheet[1]], ["id", "question", "failure type", "reason"])
        self.assertEqual(sheet.max_row - 1, 120 - passed)

    def test_formula_in_a_question_stays_text_in_the_export(self):
        path = make_sample.write("mock", self.samples)
        book = load_workbook(path)
        for row in book["Cases"].iter_rows(min_row=2):
            if row[1].value == "Exam":
                row[3].value = '=HYPERLINK("http://evil","x")'
                row[3].data_type = "s"  # text that looks like a formula, as a tester could type it
        book.save(path)
        self.upload(self.client("qc.one"), path=path)
        version = self.query("SELECT id FROM versions")[0]["id"]
        self.post(self.client("ba.one"), f"/eval-sets/version/{version}/lock")
        client = self.client("qc.one")
        run_id = self.start(client, version)
        self.review_all_needed(client, run_id, "Fail")
        sheet = load_workbook(io.BytesIO(client.get(f"/runs/{run_id}/fail-list.xlsx").data)).active
        cell = sheet.cell(row=2, column=2)
        self.assertEqual((cell.data_type, cell.value), ("s", '=HYPERLINK("http://evil","x")'))

    def test_real_formula_with_no_value_is_refused(self):
        path = make_sample.write("mock", self.samples)
        book = load_workbook(path)
        book["Cases"]["D2"] = "=1+1"
        book.save(path)
        self.assertIn(b"Validation failed: 1 error", self.upload(self.client("qc.one"), path=path).data)

    def test_review_validation(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version)
        result = self.query("SELECT id FROM results WHERE run_id=? LIMIT 1", run_id)[0]["id"]
        url = f"/runs/{run_id}/review/{result}"
        self.assertEqual(self.post(client, url).status_code, 400)
        no_owner = self.post(client, url + "?tab=review&chip=all", qc_result="Fail", note="keep this note")
        self.assertEqual(no_owner.status_code, 400)
        self.assertIn(b"A failed case needs an owner", no_owner.data)
        self.assertIn(b'>keep this note</textarea>', no_owner.data)
        self.assertEqual(self.post(client, url, qc_result="Fail", owner="Bot").status_code, 400)
        self.assertEqual(self.post(client, url, qc_result="Fail", owner="Document").status_code, 302)
        self.assertEqual(self.post(self.client("ba.one"), url, qc_result="Pass").status_code, 403)
        # Owner is dropped on Pass, and each save is kept.
        self.post(client, url, qc_result="Pass", owner="Bot", failure_type=MADE_UP)
        rows = self.query("SELECT qc_result, owner FROM reviews WHERE result_id=? ORDER BY id", result)
        self.assertEqual([tuple(r) for r in rows], [("Fail", "Document"), ("Pass", None)])

    def test_stopped_run_keeps_nothing_and_error_has_no_case_text(self):
        version = self.locked_version()
        self.chat.fail_case = "MOCK-072"
        client = self.client("qc.one")
        run_id = self.start(client, version)
        run = self.query("SELECT * FROM runs WHERE id=?", run_id)[0]
        self.assertEqual((run["status"], run["done"]), ("Failed", 72))
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=?", run_id)[0][0], 0)
        page = client.get(f"/runs/{run_id}").data.decode()
        self.assertIn("Call chatbot failed at case 72 of 120", page)
        self.assertIn("Call chatbot 71/120", page)
        self.assertIn("Copy error details", page)
        self.assertNotIn("Câu hỏi mẫu", page)
        self.chat.fail_case = None
        second = self.start(client, version)
        self.assertTrue(self.query("SELECT name FROM runs WHERE id=?", second)[0]["name"].endswith("-r2"))

    def test_wrong_build_stops_at_validation(self):
        version = self.locked_version()
        run_id = self.start(self.client("qc.one"), version, build="b100")
        run = self.query("SELECT status, error, step FROM runs WHERE id=?", run_id)[0]
        self.assertEqual((run["status"], run["step"]), ("Failed", 0))
        self.assertIn("QA environment", run["error"])

    def test_new_run_rules(self):
        client = self.client("qc.one")
        self.upload(client)
        draft = self.query("SELECT id FROM versions")[0]["id"]
        form = {"product": "ChatHRMS", "set": "Exam", "version": draft, "build": "b118", "run_type": "Official",
                "milestone": "M1 gate", "quick_checks": "on"}
        self.assertIn(b"No locked version yet", client.get("/runs/new").data)
        for run_type in ("Official", "Dry run", "Rerun after fix"):
            self.assertIn(b"Choose a locked version", self.post(client, "/runs/new", **form | {"run_type": run_type}).data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM runs")[0][0], 0)
        version = self.locked_version()
        dry = self.start(client, version, run_type="Dry run", milestone="", quick_checks="")
        run = self.query("SELECT name, milestone FROM runs WHERE id=?", dry)[0]
        self.assertEqual(tuple(run), ("ChatHRMS-exam-dry-gs1-b118", None))
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=? AND sample IS NOT NULL", dry)[0][0], 0)
        self.assertIn(b"not reviewed", client.get(f"/runs/{dry}?tab=review").data)
        no_tick = form | {"version": version, "quick_checks": ""}
        self.assertIn(b"Quick checks", self.post(client, "/runs/new", **no_tick).data)
        no_addon = form | {"version": version, "set": "Add-on"}
        self.assertIn(b"no Add-on cases", self.post(client, "/runs/new", **no_addon).data)
        self.assertEqual(self.post(self.client("ba.one"), "/runs/new", **form).status_code, 403)

    def test_safety_run_reports_leaks(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version, set="Safety")
        self.assertEqual(self.query("SELECT name FROM runs WHERE id=?", run_id)[0]["name"], "ChatHRMS-safety-M1-gs1-b118")
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=?", run_id)[0][0], 20)
        self.review_all_needed(client, run_id)
        page = client.get(f"/runs/{run_id}").data.decode()
        self.assertIn("Sensitive data leaks", page)
        self.assertNotIn("Made-up statement rate", page)

    def test_bot_text_is_escaped(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version)
        conn = database.connect(self.db_path)
        with conn:
            conn.execute("UPDATE results SET scored=? WHERE run_id=?", ("<script>alert(1)</script>", run_id))
        conn.close()
        case_id = self.query("SELECT c.case_id FROM results r JOIN cases c ON c.id=r.case_row WHERE r.run_id=? LIMIT 1", run_id)[0][0]
        page = client.get(f"/runs/{run_id}?tab=review&chip=all&case={case_id}").data
        self.assertNotIn(b"<script>alert(1)", page)
        self.assertIn(b"&lt;script&gt;alert(1)", page)


class Look(Portal):
    def test_made_up_statement_is_highlighted_and_escaped(self):
        reason = {"Groundedness": {"pass": False, "reason": 'The statement "<b>90 days</b>" is not supported.'}}
        with self.app.app_context():
            marked = mark_made_up("Click Save. <b>90 days</b> [c1]", reason)
            self.assertEqual(str(marked), "Click Save. &lt;b&gt;<mark>&lt;b&gt;90 days&lt;/b&gt;</mark> [c1]".replace("&lt;b&gt;<mark>", "<mark>"))
            passed = {"Groundedness": {"pass": True, "reason": 'x "Click"'}}
            self.assertEqual(mark_made_up("Click Save.", passed), "Click Save.")

    def test_tag_shows_only_while_a_mock_is_in_use(self):
        self.assertIn(b"Mock data", self.app.test_client().get("/login").data)
        real = create_app({"TESTING": True, "SECRET_KEY": "test", "DB_PATH": self.db_path, "CHAT": object(), "JUDGE": object()})
        self.assertNotIn(b"Mock data", real.test_client().get("/login").data)


class Baseline(Portal):
    def baseline_run(self):
        version = self.locked_version()
        client = self.client("qc.one")
        return client, self.start(client, version, milestone="Baseline")

    def test_judge_is_hidden_until_independent_50_is_done(self):
        client, run_id = self.baseline_run()
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=? AND sample='independent'", run_id)[0][0], 50)
        self.assertEqual(self.query("SELECT COUNT(*) FROM results WHERE run_id=? AND sample='random15'", run_id)[0][0], 0)
        fail_case = self.query("SELECT r.id, c.case_id FROM results r JOIN cases c ON c.id=r.case_row "
                               "WHERE r.run_id=? AND r.sample='independent' AND r.judge_pass=0 LIMIT 1", run_id)[0]
        url = f"/runs/{run_id}?tab=review&chip=fail&case={fail_case['case_id']}"
        page = client.get(url).data.decode()
        self.assertIn("Hidden until you save", page)
        self.assertNotIn("Reason:", page)
        self.assertNotIn('class="b bad"', page)  # no Fail badge in the list either
        self.assertIn('aria-current="true">Independent 50', page)
        self.assertIn("stays closed until Independent 50", client.get(f"/runs/{run_id}?tab=report").data.decode())
        self.assertNotIn("<th>Category</th>", client.get(f"/runs/{run_id}").data.decode())

    def test_review_panel_lists_what_to_check_without_leaking_the_judge(self):
        client, run_id = self.baseline_run()
        row = self.query("SELECT r.id, c.case_id FROM results r JOIN cases c ON c.id=r.case_row WHERE r.run_id=? AND r.sample='independent' "
                         "AND r.judge_pass=0 AND c.data LIKE '%Answer with a source%' LIMIT 1", run_id)[0]
        page = client.get(f"/runs/{run_id}?tab=review&case={row['case_id']}").data.decode()
        for check in ("Behavior", "Key facts", "Groundedness", "Citation"):
            self.assertIn(f"<b>{check}</b>", page)
        self.assertIn("Eval set expects", page)
        self.assertNotIn('class="b run">Judge Fail', page)
        self.assertNotIn('class="miss"', page)
        self.assertNotIn("the judge found it", page)
        # What the chatbot retrieved is not the judge's, so QC sees it while blind: the mock retrieves the key facts.
        context = self.query("SELECT context FROM results WHERE id=?", row["id"])[0]["context"]
        self.assertTrue(context.strip())
        self.assertIn(f'role="region" aria-labelledby="ctx-label">{html.escape(context)}</div>', page)
        saved = self.post(client, f"/runs/{run_id}/review/{row['id']}", qc_result="Pass", chip="independent")
        page = client.get(saved.headers["Location"]).data.decode()
        self.assertIn('class="b run">Judge Fail', page)
        self.assertIn('class="b bad"', page)
        self.assertIn("the judge found it", page)

    def test_a_run_from_before_the_context_was_kept_says_so(self):
        client, run_id = self.baseline_run()
        row = self.query("SELECT r.id, c.case_id FROM results r JOIN cases c ON c.id=r.case_row WHERE r.run_id=? AND r.sample='independent' "
                         "AND c.data LIKE '%Answer with a source%' LIMIT 1", run_id)[0]
        conn = database.connect(self.db_path)
        with conn:
            conn.execute("UPDATE results SET context=NULL WHERE id=?", (row["id"],))
        conn.close()
        page = client.get(f"/runs/{run_id}?tab=review&case={row['case_id']}").data.decode()
        self.assertIn("Not kept for this run", page)

    def test_saving_reveals_that_case_only(self):
        client, run_id = self.baseline_run()
        row = self.query("SELECT r.id, c.case_id FROM results r JOIN cases c ON c.id=r.case_row "
                         "WHERE r.run_id=? AND r.sample='independent' AND r.judge_pass=0 LIMIT 1", run_id)[0]
        saved = self.post(client, f"/runs/{run_id}/review/{row['id']}", qc_result="Pass", chip="independent")
        self.assertIn(row["case_id"], saved.headers["Location"])
        page = client.get(saved.headers["Location"]).data.decode()
        self.assertNotIn("Hidden until you save", page)
        self.assertIn("Hidden", page)  # the rest of the list
        self.assertIn("Next unreviewed", page)

    def test_other_cases_cannot_be_saved_while_blind(self):
        client, run_id = self.baseline_run()
        other = self.query("SELECT id FROM results WHERE run_id=? AND sample IS NULL LIMIT 1", run_id)[0]["id"]
        self.assertEqual(self.post(client, f"/runs/{run_id}/review/{other}", qc_result="Pass").status_code, 409)

    def test_rates_use_the_verdict_saved_before_the_judge_was_shown(self):
        client, run_id = self.baseline_run()
        rows = self.query("SELECT id, judge_pass FROM results WHERE run_id=? AND sample='independent'", run_id)
        first_pass = next(r for r in rows if r["judge_pass"])
        for row in rows:
            result = "Pass" if row["judge_pass"] else "Fail"
            form = {"qc_result": result} if result == "Pass" else {"qc_result": "Fail", "owner": "Bot", "failure_type": MADE_UP}
            if row["id"] == first_pass["id"]:
                form = {"qc_result": "Fail", "owner": "Bot", "failure_type": MADE_UP}
            self.post(client, f"/runs/{run_id}/review/{row['id']}", **form)
        self.post(client, f"/runs/{run_id}/review/{first_pass['id']}", qc_result="Pass")
        self.review_all_needed_after_blind(client, run_id)
        page = client.get(f"/runs/{run_id}").data.decode()
        passes = sum(1 for r in rows if r["judge_pass"])
        self.assertIn(f"False pass (independent): <b>1 / {passes}", page)

    def review_all_needed_after_blind(self, client, run_id):
        rows = self.query("SELECT r.id FROM results r WHERE r.run_id=? AND r.judge_pass=0 "
                          "AND NOT EXISTS (SELECT 1 FROM reviews v WHERE v.result_id=r.id)", run_id)
        for row in rows:
            self.post(client, f"/runs/{run_id}/review/{row['id']}", qc_result="Fail", owner="Bot", failure_type=MADE_UP)


class ReviewFlow(Portal):
    def run_with_lists(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version)
        rows = self.query("SELECT r.id, c.case_id, r.judge_pass, r.sample FROM results r JOIN cases c ON c.id=r.case_row "
                          "WHERE r.run_id=? ORDER BY c.id", run_id)
        fails = [r for r in rows if not r["judge_pass"]]
        randoms = [r for r in rows if r["sample"] == "random15"]
        return client, run_id, fails, randoms

    def open_case(self, page):
        found = re.search(r'<a class="item \w+ sel" href="[^"]*" aria-current="true">\s*<span class="ihead"><b class="mono">([^<]+)<', page)
        return found and found[1]

    def save_fail(self, client, run_id, row, chip):
        return self.post(client, f"/runs/{run_id}/review/{row['id']}", qc_result="Fail", owner="Bot", failure_type=MADE_UP, chip=chip)

    def test_review_opens_no_case_until_qc_picks_one(self):
        client, run_id, fails, randoms = self.run_with_lists()
        page = client.get(f"/runs/{run_id}?tab=review").data.decode()
        self.assertIsNone(self.open_case(page))
        self.assertNotIn('id="review-form"', page)
        self.assertIn(f'aria-current="true">Judge Fail {len(fails)} · {len(fails)} left', page)
        page = client.get(f"/runs/{run_id}?tab=review&chip=fail&case={fails[1]['case_id']}").data.decode()
        self.assertEqual(self.open_case(page), fails[1]["case_id"])
        self.assertIn('id="review-form"', page)
        for row in fails:
            self.save_fail(client, run_id, row, "fail")
        page = client.get(f"/runs/{run_id}?tab=review").data.decode()
        self.assertIn('aria-current="true">Random', page)  # Judge Fail is done, so Random is the list shown
        self.assertIn(f"Judge Fail {len(fails)} · done", page)
        self.assertIsNone(self.open_case(page))

    def test_save_moves_on_and_crosses_to_the_next_list(self):
        client, run_id, fails, randoms = self.run_with_lists()
        first = self.save_fail(client, run_id, fails[0], "fail").headers["Location"]
        self.assertIn(f"case={fails[1]['case_id']}", first)
        self.assertIn(f"saved={fails[0]['case_id']}", first)
        for row in fails[1:-1]:
            self.save_fail(client, run_id, row, "fail")
        crossed = self.save_fail(client, run_id, fails[-1], "fail").headers["Location"]
        self.assertIn("chip=random", crossed)
        self.assertIn(f"case={randoms[0]['case_id']}", crossed)
        self.assertIn("Next list: Random", client.get(crossed).data.decode())

    def test_browsing_all_stays_on_the_saved_case(self):
        client, run_id, fails, _ = self.run_with_lists()
        location = self.save_fail(client, run_id, fails[0], "all").headers["Location"]
        self.assertIn(f"case={fails[0]['case_id']}", location)

    def test_finishing_shows_the_way_out_and_only_qc_can_export(self):
        client, run_id, _, _ = self.run_with_lists()
        self.review_all_needed(client, run_id)
        page = client.get(f"/runs/{run_id}?tab=review").data.decode()
        self.assertIn("Review complete", page)
        self.assertIn("Export Fail list", page)
        self.assertNotIn("Export Fail list", self.client("ba.one").get(f"/runs/{run_id}?tab=review").data.decode())

    def test_failure_type_starts_from_the_failing_metric(self):
        client, run_id, fails, _ = self.run_with_lists()
        metrics = json.loads(self.query("SELECT metrics FROM results WHERE id=?", fails[0]["id"])[0]["metrics"])
        page = client.get(f"/runs/{run_id}?tab=review&chip=fail&case={fails[0]['case_id']}").data.decode()
        self.assertIn(f"<option selected>{suggested_failure(metrics)}</option>", page)
        self.assertIn("Filled in from the judge", page)

    def test_nothing_about_the_judge_leaks_while_blind(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version, milestone="Baseline")
        rows = self.query("SELECT r.id, c.case_id, r.judge_pass FROM results r JOIN cases c ON c.id=r.case_row "
                          "WHERE r.run_id=? AND r.sample='independent'", run_id)
        failed = next(r for r in rows if not r["judge_pass"])
        # A crafted saved= on a case nobody has saved must not name the verdict.
        page = client.get(f"/runs/{run_id}?tab=review&case={failed['case_id']}&saved={failed['case_id']}").data.decode()
        self.assertNotIn("the judge said", page)
        self.assertNotIn("Filled in from the judge", page)
        self.assertIsNone(re.search(r"<option selected>(Wrong behavior|Missing key facts|Made-up statement|Wrong document|System error)", page))
        self.assertIn("Reviewed <b>0 / 50</b>", page)
        for chip in ("Judge Fail", "All"):  # closed chips show no count
            self.assertIn(f'<span class="chip off">{chip}</span>', page)
        saved = self.post(client, f"/runs/{run_id}/review/{failed['id']}", qc_result="Pass", chip="independent")
        self.assertIn("You said Pass; the judge said Fail", client.get(saved.headers["Location"]).data.decode())


class Guidance(Portal):
    def test_new_run_starts_on_a_locked_version_and_no_milestone(self):
        locked = self.locked_version()
        client = self.client("qc.one")
        self.upload(client)  # a newer Draft, listed first
        page = client.get("/runs/new").data.decode()
        self.assertRegex(page, rf'<option value="{locked}" data-tag="gs1" selected>')
        self.assertNotIn("Draft", page)
        self.assertIn('<option value="" selected>Choose a milestone', page)

    def test_lock_tells_ba_the_label_first_and_after(self):
        client = self.client("qc.one")
        self.upload(client)
        ba = self.client("ba.one")
        self.assertIn("Lock as gs1? A locked version cannot change.", ba.get("/eval-sets").data.decode())
        version = self.query("SELECT id FROM versions")[0]["id"]
        done = self.post(ba, f"/eval-sets/version/{version}/lock")
        self.assertIn("Locked as gs1.", ba.get(done.headers["Location"]).data.decode())
        self.assertNotIn("Locked as gs9.", ba.get("/eval-sets?locked=gs9").data.decode())

    def test_targets_show_only_after_review_on_exam(self):
        version = self.locked_version()
        client = self.client("qc.one")
        run_id = self.start(client, version)
        self.assertNotIn("team target", client.get(f"/runs/{run_id}").data.decode())
        self.review_all_needed(client, run_id, "Fail")
        page = client.get(f"/runs/{run_id}").data.decode()
        self.assertIn("team target ≥ 85%", page)
        self.assertIn("Team targets, not client commitments", page)
        safety = self.start(client, version, set="Safety")
        self.review_all_needed(client, safety)
        self.assertNotIn("team target", client.get(f"/runs/{safety}").data.decode())

    def test_runs_list_explains_why_it_is_empty(self):
        client = self.client("qc.one")
        self.assertIn("No runs yet", client.get("/runs").data.decode())
        self.assertIn("No runs match these filters", client.get("/runs?product=ChatHRMS").data.decode())


class Comparison(Portal):
    def completed_review(self, client, run_id):
        rows = self.query("SELECT id, judge_pass FROM results WHERE run_id=? AND (judge_pass=0 OR sample IS NOT NULL)", run_id)
        for row in rows:
            form = {"qc_result": "Pass"} if row["judge_pass"] else {"qc_result": "Fail", "owner": "Bot", "failure_type": MADE_UP}
            self.post(client, f"/runs/{run_id}/review/{row['id']}", **form)

    def test_comparison_across_versions_uses_unchanged_cases(self):
        client = self.client("qc.one")
        gs1 = self.locked_version()
        first = self.start(client, gs1, milestone="M1 gate")
        self.completed_review(client, first)
        gs2 = self.locked_version()
        second = self.start(client, gs2, milestone="UAT entry")
        self.completed_review(client, second)
        listing = client.get("/runs").data.decode()
        self.assertIn("first run", listing)
        self.assertIn('+0.0 pp <span class="b neu">within margin', listing)
        self.assertIn("Regression 0", client.get(f"/runs/{second}?tab=review").data.decode())

    def test_dry_run_is_not_compared(self):
        client = self.client("qc.one")
        version = self.locked_version()
        dry = self.start(client, version, run_type="Dry run", milestone="", quick_checks="")
        official = self.start(client, version)
        self.completed_review(client, official)
        listing = client.get("/runs").data.decode()
        self.assertIn("Dry run", listing)
        self.assertIn("first run", listing)

    def test_filter_by_version(self):
        client = self.client("qc.one")
        gs1 = self.locked_version()
        self.start(client, gs1)
        self.locked_version()
        page = client.get("/runs?product=ChatHRMS&set=Exam&version=gs2").data.decode()
        self.assertNotIn("ChatHRMS-exam-M1-gs1", page)


if __name__ == "__main__":
    unittest.main()
