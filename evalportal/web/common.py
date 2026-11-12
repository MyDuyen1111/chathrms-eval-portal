"""What every page shares: the blueprint, the database, sign-in and role checks, template helpers."""
import hmac
import re
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, abort, current_app, g, redirect, request, session, url_for
from markupsafe import Markup

from .. import db as database
from .. import judgeconfig
from ..i18n import lang, t
from ..judge import RouterJudge
from ..mocks import MockChat, MockJudge

bp = Blueprint("portal", __name__)


def _now():
    return datetime.now(timezone.utc)


def _stamp():
    return _now().isoformat(timespec="seconds")


def products():
    """ChatHRMS, on MockChat or the real bot (see create_app)."""
    return current_app.config["PRODUCTS"]


def get_db():
    if "db" not in g:
        g.db = database.connect(current_app.config["DB_PATH"])
    return g.db


@bp.teardown_app_request
def _close_db(_error):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


bp.add_app_template_global(t)
bp.add_app_template_global(lang)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@bp.app_template_global()
def csrf_field():
    """The hidden input every POST form carries; _guard rejects a POST without it."""
    return Markup('<input type="hidden" name="_csrf" value="{}">').format(csrf_token())


@bp.app_template_filter()
def rate(pair):
    return f"{pair[0] / pair[1] * 100:.1f}%" if pair and pair[1] else "—"


@bp.app_template_filter()
def count(pair):
    return f"{pair[0]} / {pair[1]}" if pair else "—"


@bp.app_template_filter()
def margin_badge(text):
    number, margin, _ = text.partition(" within margin")
    if margin:
        return Markup('{} <span class="b neu">within margin</span>').format(number)
    return text if text[0] in "+-" else Markup('<span class="dim">{}</span>').format(t(text))


@bp.app_template_filter()
def mark_made_up(text, metrics):
    """Highlight the statement the judge says is not in the documents, when its reason quotes it."""
    grounded = metrics.get("Groundedness") or {}
    quoted = re.search(r'"([^"]+)"', grounded.get("reason") or "")
    if grounded.get("pass", True) or not quoted or quoted[1] not in text:
        return text
    before, after = text.split(quoted[1], 1)
    return Markup("{}<mark>{}</mark>{}").format(before, quoted[1], after)


def _saved_judge(saved):
    path = judgeconfig.key_path(current_app.config["DB_PATH"])
    # A missing key stops the run with the router's 401. Falling back to the mock would hide it behind made-up verdicts.
    return RouterJudge(saved, path.read_text() if path.exists() else "")


def _current_judge():
    """The judge a new run gets. Case text leaves the portal only after the Administrator turns the router on."""
    saved = get_db().execute("SELECT * FROM judge_settings ORDER BY id DESC LIMIT 1").fetchone()
    return _saved_judge(saved) if saved and saved["in_use"] else current_app.config["JUDGE"]


@bp.app_template_global()
def using_mocks():
    return isinstance(current_app.config["CHAT"], MockChat) or isinstance(_current_judge(), MockJudge)


ADMIN_ENDPOINTS = ("portal.home", "portal.users", "portal.reset_password", "portal.set_disabled", "portal.judge_settings",
                   "portal.test_judge", "portal.password", "portal.logout")


@bp.before_app_request
def _guard():
    if request.endpoint == "static":
        return None
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not hmac.compare_digest(sent, session.get("csrf", "\0")):
            abort(400, t("The form expired. Go back, reload the page and try again."))
    g.user = None
    if "uid" in session:
        user = get_db().execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
        if user and not user["disabled"] and hmac.compare_digest(user["session_token"], session.get("token", "")):
            g.user = user
        else:
            session.clear()
    if request.endpoint in ("portal.login", "portal.set_language"):
        return None
    if g.user is None:
        return redirect(url_for("portal.login"))
    if g.user["must_change"] and request.endpoint not in ("portal.password", "portal.logout"):
        return redirect(url_for("portal.password"))
    # §4.2 keeps whoever grants accounts out of the Exam data. Denied here so a new page starts closed.
    if g.user["role"] == "Administrator" and request.endpoint not in ADMIN_ENDPOINTS:
        abort(403)
    return None


@bp.after_app_request
def _headers(response):
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if not request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"  # pages show Exam content
    return response


def needs_role(role):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def _temporary_password():
    return secrets.token_urlsafe(12)
