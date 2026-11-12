"""Storage. shortcut: SQLite stands in until the real database arrives; replace connect() and the SQL then."""
import sqlite3

USERS = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL CHECK(role IN ('BA','QC','Administrator')),
  pw_hash TEXT NOT NULL, must_change INTEGER NOT NULL DEFAULT 1, disabled INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0, locked_until TEXT, session_token TEXT NOT NULL, last_signin TEXT);
"""

SCHEMA = USERS + """
CREATE TABLE IF NOT EXISTS versions(
  id INTEGER PRIMARY KEY, product TEXT NOT NULL, label TEXT,
  status TEXT NOT NULL CHECK(status IN ('Draft','Locked','Replaced')),
  filename TEXT NOT NULL, uploaded_by TEXT NOT NULL, uploaded_at TEXT NOT NULL,
  locked_by TEXT, locked_at TEXT, UNIQUE(product, label));

CREATE TABLE IF NOT EXISTS cases(
  id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES versions(id),
  case_id TEXT NOT NULL, set_name TEXT NOT NULL, data TEXT NOT NULL, content_hash TEXT NOT NULL,
  UNIQUE(version_id, case_id));

CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, product TEXT NOT NULL, set_name TEXT NOT NULL,
  version_id INTEGER NOT NULL REFERENCES versions(id), version_label TEXT NOT NULL, build TEXT NOT NULL,
  milestone TEXT, run_type TEXT NOT NULL, judge_prompt TEXT,
  status TEXT NOT NULL DEFAULT 'Running', step INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, error TEXT,
  started_by TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, telemetry TEXT);

CREATE TABLE IF NOT EXISTS results(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id),
  case_row INTEGER NOT NULL REFERENCES cases(id), turns TEXT NOT NULL, scored TEXT NOT NULL,
  citations TEXT NOT NULL, metrics TEXT NOT NULL, rules TEXT NOT NULL,
  judge_pass INTEGER NOT NULL, sample TEXT, context TEXT);

-- Append-only: the latest row is the review, and the rows keep who decided what and when.
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY, result_id INTEGER NOT NULL REFERENCES results(id),
  qc_result TEXT NOT NULL, owner TEXT, failure_type TEXT, wrong_location INTEGER NOT NULL DEFAULT 0,
  note TEXT NOT NULL DEFAULT '', reviewed_by TEXT NOT NULL, reviewed_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reviews_by_result ON reviews(result_id, id);
CREATE INDEX IF NOT EXISTS results_by_run ON results(run_id);

-- Append-only: the latest row is the setting, and the rows keep who changed what and when. The API key is never here.
CREATE TABLE IF NOT EXISTS judge_settings(
  id INTEGER PRIMARY KEY, endpoint TEXT NOT NULL, model TEXT NOT NULL,
  reasoning_effort TEXT NOT NULL, key_changed INTEGER NOT NULL, changed_by TEXT NOT NULL, changed_at TEXT NOT NULL,
  in_use INTEGER NOT NULL DEFAULT 0);
"""


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _drop_is_admin(conn):
    # The first schema made the two leads admins through is_admin and allowed only BA or QC. SQLite cannot change a CHECK in place.
    if conn.execute("SELECT 1 FROM pragma_table_info('users') WHERE name='is_admin'").fetchone():
        columns = "id, name, username, role, pw_hash, must_change, disabled, failed, locked_until, session_token, last_signin"
        conn.executescript(f"""
            BEGIN;
            ALTER TABLE users RENAME TO users_old;
            {USERS}
            INSERT INTO users({columns}) SELECT {columns} FROM users_old;
            DROP TABLE users_old;
            COMMIT;""")


def _judge_settings_for_a_router(conn):
    # The first version of this table followed Azure's deployment and api_version; a router only takes a model name.
    if conn.execute("SELECT 1 FROM pragma_table_info('judge_settings') WHERE name='api_version'").fetchone():
        conn.executescript("""
            BEGIN;
            ALTER TABLE judge_settings RENAME COLUMN deployment TO model;
            ALTER TABLE judge_settings DROP COLUMN api_version;
            COMMIT;""")


def _add_column(conn, table, column, definition):
    existing = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    if existing and column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init(path):
    conn = connect(path)
    _drop_is_admin(conn)
    _judge_settings_for_a_router(conn)
    # Settings saved before the switch existed stay off, so an upgrade sends no case text to the router.
    _add_column(conn, "judge_settings", "in_use", "INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "runs", "telemetry", "TEXT")
    # What the chatbot retrieved, so QC can check Groundedness by eye. NULL on runs made before it was kept.
    _add_column(conn, "results", "context", "TEXT")
    conn.executescript(SCHEMA)
    # shortcut: runs live in one app process, so a restart ends them; use a job queue when hosting needs several workers.
    with conn:
        conn.execute("UPDATE runs SET status='Failed', error=? WHERE status='Running'",
                     ("The portal restarted during this run. Start the run again.",))
    conn.close()
