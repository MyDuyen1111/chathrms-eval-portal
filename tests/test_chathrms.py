"""The ChatHRMS practice portal: its chat client against a fake ChatHRMS API, and a whole run through the pages."""
import json
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from evalportal.chatapi import normalize
from evalportal.chathrms import ChatHRMSChat
from tests.test_web import Portal

STAFF, ADMIN = "staff-password-1", "admin-password-1"
WFH = "KB01_HR_Quy dinh lam viec tu xa_01.11.2026"


class FakeChatHRMS(BaseHTTPRequestHandler):
    """Login with one password for HR01/ADMIN01 and one for employees; salary questions take the rule path."""

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/api/auth/login":
            body = json.loads(raw)
            user = body["employee_code"]
            self.server.logins.append((user, body["password"]))
            if body["password"] != (ADMIN if user in ("HR01", "ADMIN01") else STAFF):
                return self.reply(401, {"detail": "Sai mã nhân viên hoặc mật khẩu"})
            return self.reply(200, {"access_token": f"token-{user}"})
        fields = dict(urllib.parse.parse_qsl(raw.decode()))
        self.server.chats.append((self.headers["Authorization"], fields))
        if "thú cưng" in fields["message"]:  # CH-011: the LLM call timed out inside ChatHRMS
            trace = {"route": "fallback:ai_unavailable", "tools": [], "context": []}
            text = "AI tạm không khả dụng."
        elif "lương" in fields["message"]:
            trace = {"route": "rule:salary", "tools": [], "context": []}
            text = "Xin lỗi, tôi không thể cung cấp thông tin lương."
        else:
            trace = {"route": "llm", "tools": ["search_hr_policy"], "context": [f"--- Tài liệu 1 (Nguồn: {WFH}) ---\nTối đa 2 ngày mỗi tuần."]}
            text = f"Tối đa 2 ngày mỗi tuần. [Nguồn: {WFH}]"
        self.reply(200, {"response": text, "tool_call": None, "conversation_id": fields.get("conversation_id", "c-1"), "trace": trace})

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def fake_server(test):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeChatHRMS)
    server.logins, server.chats = [], []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test.addCleanup(server.server_close)
    test.addCleanup(server.shutdown)
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class Normalize(unittest.TestCase):
    def test_route_and_tags_become_outcome_and_citations(self):
        turn = normalize({"response": "A [Nguồn: KB01; KB02] B [Nguồn: KB01]",
                                      "trace": {"route": "llm", "context": ["chunk"]}, "correlationId": "x"})
        self.assertEqual(turn["outcome"], "answered")
        self.assertEqual([c["document"] for c in turn["citations"]], ["KB01", "KB02"])
        self.assertEqual(turn["correlation_id"], "x")
        self.assertEqual(normalize({"response": "Không", "trace": {"route": "rule:salary", "context": []}})["outcome"],
                         "non_knowledge")
        self.assertEqual(normalize({"response": "", "trace": {"route": "fallback:offline_policy_search",
                                                                          "context": ["chunk"]}})["outcome"], "unavailable")
        draft = normalize({"response": "Xác nhận?", "trace": {"route": "rule:ticket_workflow"}})
        self.assertEqual(draft["turn_type"], "confirmation")


class Client(unittest.TestCase):
    def test_signs_in_with_either_password_and_keeps_the_conversation(self):
        server, url = fake_server(self)
        chat = ChatHRMSChat(url, (STAFF, ADMIN))
        conversation = chat.new_conversation("ChatHRMS", {"user": "HR01"})
        self.assertEqual([password for _, password in server.logins], [STAFF, ADMIN])
        status, body = chat.send(conversation, "WFH mấy ngày?")
        self.assertEqual(status, 200)
        chat.send(conversation, "còn gì nữa?")
        self.assertEqual(server.chats[0], ("Bearer token-HR01", {"message": "WFH mấy ngày?"}))
        self.assertEqual(server.chats[1][1]["conversation_id"], "c-1")
        self.assertIn("2 ngày", chat.retrieved_context("ChatHRMS", body["correlationId"]))
        self.assertEqual(chat.retrieved_context("ChatHRMS", body["correlationId"]), "")
        with self.assertRaises(TimeoutError):
            chat.send(conversation, "mang thú cưng được không?")

    def test_refusals_reach_the_runner_as_statuses(self):
        _, url = fake_server(self)
        wrong = ChatHRMSChat(url, ("wrong-password",)).new_conversation("ChatHRMS", {"user": "NV001"})
        self.assertEqual(ChatHRMSChat(url, ("wrong-password",)).send(wrong, "hi")[0], 401)
        unset = ChatHRMSChat(url, (None, "")).new_conversation("ChatHRMS", {"user": "NV001"})
        self.assertEqual(unset["refused"][1]["code"], "no_password")
        down = ChatHRMSChat("http://127.0.0.1:1", (STAFF,)).new_conversation("ChatHRMS", {"user": "NV001"})
        self.assertEqual(down["refused"], (503, {"code": "unreachable"}))


class PracticePortal(Portal):
    def setUp(self):
        super().setUp()
        self.server, url = fake_server(self)
        self.app.config.update(CHAT=ChatHRMSChat(url, (STAFF, ADMIN)))

    def test_only_chathrms_is_offered(self):
        client = self.client("qc.one")
        self.assertIn(b"ChatHRMS", client.get("/eval-sets").data)
        self.assertEqual(client.get("/eval-sets?product=Other").status_code, 404)
        self.assertEqual(self.post(client, "/eval-sets/Other/upload").status_code, 404)

    def test_a_run_asks_each_case_as_its_user(self):
        version = self.locked_version("exam")
        run_id = self.start(self.client("qc.one"), version, product="ChatHRMS", build="live")
        run = self.query("SELECT status, error, total FROM runs WHERE id=?", run_id)[0]
        self.assertEqual((run["status"], run["error"], run["total"]), ("Completed", None, 14))
        self.assertIn(("HR01", ADMIN), self.server.logins)
        self.assertEqual({auth for auth, _ in self.server.chats} - {f"Bearer token-NV00{i}" for i in range(1, 9)},
                         {"Bearer token-HR01"})
        timed_out = self.query("SELECT r.metrics FROM results r JOIN cases c ON c.id=r.case_row WHERE c.case_id='CH-011'")[0]
        self.assertEqual(json.loads(timed_out["metrics"])["System error"]["reason"], "Timeout")
        self.assertEqual(sum("thú cưng" in fields["message"] for _, fields in self.server.chats), 2)  # retried once
        cited = self.query("SELECT r.citations FROM results r JOIN cases c ON c.id=r.case_row WHERE c.case_id='CH-001'")[0]
        self.assertEqual(json.loads(cited["citations"])[0]["document"], WFH)
