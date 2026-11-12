"""Server commands: check-judge and create-admin."""
import secrets

import click
from werkzeug.security import generate_password_hash

from .. import db as database
from .. import judgecheck, runner
from .common import _saved_judge, _temporary_password


def register_cli(app):
    @app.cli.command("check-judge")
    def check_judge():
        """Grade the handbook's examples with the saved judge settings. Sends no eval set case, and needs no switch turned on."""
        conn = database.connect(app.config["DB_PATH"])
        saved = conn.execute("SELECT * FROM judge_settings ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        if saved is None:
            raise click.ClickException("Save the judge settings on the Judge page first.")
        judge = _saved_judge(saved)
        try:
            results = judgecheck.run(judge)
        except runner.RunStopped as stop:
            raise click.ClickException(str(stop))
        wrong = [result for result in results if result[2] != result[3]]
        for source, name, expected, got in results:
            click.echo(f"{'ok   ' if expected == got else 'WRONG'} {source:8} {name}" + ("" if expected == got else f": expected {expected}, got {got}"))
        click.echo(f"{judge.prompt_version}: {len(results) - len(wrong)} of {len(results)} right. Models that answered: {', '.join(judge.usage['models']) or 'not reported'}.")
        if wrong:
            raise SystemExit(1)

    @app.cli.command("create-admin")
    def create_admin():
        """Create the Administrator, who then adds everyone else on the Users page. The temporary password prints once."""
        conn = database.connect(app.config["DB_PATH"])
        if conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone():
            click.echo("admin already exists")
        else:
            temporary = _temporary_password()
            with conn:
                conn.execute("INSERT INTO users(name, username, role, pw_hash, session_token) VALUES('Administrator','admin','Administrator',?,?)",
                             (generate_password_hash(temporary), secrets.token_urlsafe(32)))
            click.echo(f"admin  temporary password: {temporary}")
        conn.close()
