"""Administrator pages: Users and Judge."""
import re
import secrets

from flask import abort, current_app, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from .. import judgeconfig
from ..i18n import t
from .common import _now, _stamp, _temporary_password, bp, get_db, needs_role

USERNAME = re.compile(r"^[a-z0-9._-]{3,40}$")


@bp.route("/users", methods=["GET", "POST"])
@needs_role("Administrator")
def users():
    conn = get_db()
    message, error = None, None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        role = request.form.get("role")
        if not name or not USERNAME.match(username) or role not in ("BA", "QC"):
            error = t("Enter a name, a role, and a username of 3 to 40 lowercase letters, digits, dots, dashes or underscores.")
        elif conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            error = t("The username {username} is already taken.", username=username)
        else:
            temporary = _temporary_password()
            with conn:
                conn.execute("INSERT INTO users(name, username, role, pw_hash, session_token) VALUES(?,?,?,?,?)",
                             (name, username, role, generate_password_hash(temporary), secrets.token_urlsafe(32)))
            message = (t("User added"), username, temporary)
    return _users_page(message, error)


def _users_page(message=None, error=None):
    rows = get_db().execute("SELECT * FROM users ORDER BY role='Administrator' DESC, name").fetchall()
    return render_template("users.html", users=rows, message=message, error=error,
                           show_form=bool(error or request.args.get("add")), now=_now().isoformat())


@bp.post("/users/<int:user_id>/reset")
@needs_role("Administrator")
def reset_password(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone() or abort(404)
    # The account admin's row has no actions (§4.2 mock); its own password goes through /password.
    if user["role"] == "Administrator":
        abort(403)
    temporary = _temporary_password()
    with conn:
        conn.execute("UPDATE users SET pw_hash=?, must_change=1, failed=0, locked_until=NULL, session_token=? WHERE id=?",
                     (generate_password_hash(temporary), secrets.token_urlsafe(32), user_id))
    return _users_page((t("Password reset"), user["username"], temporary))


@bp.post("/users/<int:user_id>/<any(disable,enable):action>")
@needs_role("Administrator")
def set_disabled(user_id, action):
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone() or abort(404)
    # Nobody could bring a disabled Administrator back.
    if user["role"] == "Administrator":
        abort(403)
    with conn:
        # Accounts are never deleted, so the review history keeps its names (§4.2).
        conn.execute("UPDATE users SET disabled=? WHERE id=?", (int(action == "disable"), user_id))
    return redirect(url_for("portal.users"))


def _judge_page(message=None, error=None, typed=None):
    history = get_db().execute("SELECT * FROM judge_settings ORDER BY id DESC").fetchall()
    saved = dict(history[0]) if history else {}
    return render_template("judge.html", history=history, values=saved | (typed or {}), message=message, error=error,
                           key_saved=judgeconfig.key_path(current_app.config["DB_PATH"]).exists(),
                           efforts=judgeconfig.REASONING_EFFORTS)


@bp.route("/judge", methods=["GET", "POST"])
@needs_role("Administrator")
def judge_settings():
    if request.method == "GET":
        return _judge_page(message=t("Settings saved. Test the connection to check them.") if request.args.get("saved") else None)
    conn = get_db()
    saved = conn.execute("SELECT endpoint FROM judge_settings ORDER BY id DESC LIMIT 1").fetchone()
    path = judgeconfig.key_path(current_app.config["DB_PATH"])
    settings, key, error = judgeconfig.clean(request.form, saved["endpoint"] if saved and path.exists() else None)
    if error:
        return _judge_page(error=t(error), typed=settings)
    if key:
        judgeconfig.write_key(path, key)
    with conn:
        conn.execute("INSERT INTO judge_settings(endpoint, model, reasoning_effort, in_use, key_changed, changed_by, changed_at)"
                     " VALUES(?,?,?,?,?,?,?)", (*settings.values(), int(bool(key)), g.user["name"], _stamp()))
    return redirect(url_for("portal.judge_settings", saved=1))


@bp.post("/judge/test")
@needs_role("Administrator")
def test_judge():
    saved = get_db().execute("SELECT * FROM judge_settings ORDER BY id DESC LIMIT 1").fetchone()
    path = judgeconfig.key_path(current_app.config["DB_PATH"])
    if saved is None or not path.exists():
        return _judge_page(error=t("Save the settings and the API key first."))
    worked, text = judgeconfig.test_connection(saved, path.read_text())
    # Fixed router messages have entries; the "Connected" line and an unknown status code stay English.
    return _judge_page(message=t(text)) if worked else _judge_page(error=t(text))
