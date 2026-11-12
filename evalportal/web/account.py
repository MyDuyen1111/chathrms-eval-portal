"""Signing in and out, the viewer's own password, and the language switch."""
import secrets
from datetime import datetime, timedelta

from flask import g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..i18n import LANGUAGES, t
from .common import _now, _stamp, bp, get_db

MIN_PASSWORD = 12
MAX_FAILED_SIGNINS = 5
LOCK_MINUTES = 15
# Checked when the username is unknown, so a wrong username takes as long as a wrong password.
UNKNOWN_USER_HASH = generate_password_hash(secrets.token_hex(16))


@bp.route("/language/<code>")
def set_language(code):
    """A per-browser choice, so it works on the sign-in page too."""
    target = request.args.get("next", "")
    # Only a path on this site: an absolute or protocol-relative next would make this an open redirect.
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        target = url_for("portal.login")
    response = redirect(target)
    if code in LANGUAGES:
        response.set_cookie("lang", code, max_age=365 * 24 * 3600, samesite="Lax", httponly=True)
    return response


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?",
                            (request.form.get("username", "").strip().lower(),)).fetchone()
        password_ok = check_password_hash(user["pw_hash"] if user else UNKNOWN_USER_HASH,
                                          request.form.get("password", ""))
        locked = bool(user and user["locked_until"]) and _now() < datetime.fromisoformat(user["locked_until"])
        if user and password_ok and not locked and not user["disabled"]:
            with conn:
                conn.execute("UPDATE users SET failed=0, locked_until=NULL, last_signin=? WHERE id=?",
                             (_stamp(), user["id"]))
            session.clear()
            session.update(uid=user["id"], token=user["session_token"])
            return redirect(url_for("portal.home"))
        if user and not locked:
            failed = user["failed"] + 1
            until = (_now() + timedelta(minutes=LOCK_MINUTES)).isoformat() if failed >= MAX_FAILED_SIGNINS else None
            with conn:
                conn.execute("UPDATE users SET failed=?, locked_until=? WHERE id=?",
                             (0 if until else failed, until, user["id"]))
        error = t("The username or password is wrong, or the account is locked for a few minutes.")
    return render_template("login.html", error=error)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("portal.login"))


@bp.route("/password", methods=["GET", "POST"])
def password():
    error = None
    if request.method == "POST":
        new = request.form.get("new", "")
        if not check_password_hash(g.user["pw_hash"], request.form.get("current", "")):
            error = t("The current password is wrong.")
        elif len(new) < MIN_PASSWORD:
            error = t("The new password must have at least {minimum} characters.", minimum=MIN_PASSWORD)
        elif new != request.form.get("confirm", ""):
            error = t("The two new passwords do not match.")
        elif new == request.form.get("current", ""):
            error = t("The new password must be different from the current one.")
        else:
            token = secrets.token_urlsafe(32)
            conn = get_db()
            with conn:
                conn.execute("UPDATE users SET pw_hash=?, must_change=0, session_token=? WHERE id=?",
                             (generate_password_hash(new), token, g.user["id"]))
            session["token"] = token
            return redirect(url_for("portal.home"))
    return render_template("password.html", error=error, minimum=MIN_PASSWORD)


@bp.route("/")
def home():
    return redirect(url_for("portal.users" if g.user["role"] == "Administrator" else "portal.runs"))
