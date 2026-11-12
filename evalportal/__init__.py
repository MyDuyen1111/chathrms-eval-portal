"""Chatbot Eval Portal: upload and lock eval sets, run them, review results (QC handbook v13)."""
import os
import secrets
from pathlib import Path

from flask import Flask

from . import db
from .chathrms import ChatHRMSChat
from .mocks import MockChat, MockJudge


def _secret_key(instance_path):
    path = Path(instance_path) / "secret_key"
    if not path.exists():
        descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(secrets.token_hex(32))
    return path.read_text()


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    os.chmod(app.instance_path, 0o700)  # the database holds Exam content
    app.config.update(
        DB_PATH=str(Path(app.instance_path) / "portal.db"),
        MAX_CONTENT_LENGTH=20 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("PORTAL_HTTPS") == "1",
        # MockChat answers like ChatHRMS until CHATHRMS_URL is set. JUDGE is what runs use until the router is turned on at /judge.
        # ChatHRMS has no intent confirmation turn, so the mock answers at once unless asked.
        CHAT=MockChat(build=os.environ.get("MOCK_BUILD", "b118"), fail_case=os.environ.get("MOCK_FAIL_CASE"),
                      confirms=os.environ.get("MOCK_CONFIRM") == "1"),
        PRODUCTS=("ChatHRMS",),
        JUDGE=MockJudge(),
    )
    if chathrms_url := os.environ.get("CHATHRMS_URL"):
        app.config.update(CHAT=ChatHRMSChat(
            chathrms_url, (os.environ.get("CHATHRMS_PASSWORD"), os.environ.get("CHATHRMS_ADMIN_PASSWORD")),
            build=os.environ.get("CHATHRMS_BUILD", "live")))
    app.config.update(config or {})
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _secret_key(app.instance_path)
    db.init(app.config["DB_PATH"])

    from .web import bp, register_cli
    app.register_blueprint(bp)
    register_cli(app)
    return app
