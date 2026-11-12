"""A run's results loaded for scoring, and how they compare with the previous official run."""
import json

from .. import scoring
from .common import get_db


def load_rows(run_id):
    conn = get_db()
    latest, first = {}, {}
    for review in conn.execute("SELECT v.* FROM reviews v JOIN results r ON r.id=v.result_id WHERE r.run_id=? ORDER BY v.id", (run_id,)):
        latest[review["result_id"]] = dict(review)
        first.setdefault(review["result_id"], review["qc_result"])
    rows = []
    for row in conn.execute("SELECT r.*, c.case_id, c.data, c.content_hash FROM results r "
                            "JOIN cases c ON c.id=r.case_row WHERE r.run_id=? ORDER BY c.id", (run_id,)):
        rows.append({**json.loads(row["data"]),
                     "result_id": row["id"], "case_id": row["case_id"], "content_hash": row["content_hash"],
                     "judge_pass": bool(row["judge_pass"]), "sample": row["sample"], "scored": row["scored"],
                     "metrics": json.loads(row["metrics"]), "rules": json.loads(row["rules"]),
                     "turns": json.loads(row["turns"]), "citations": json.loads(row["citations"]), "context": row["context"],
                     "review": latest.get(row["id"]), "first_qc": first.get(row["id"])})
    return rows


def _previous_official(run):
    return get_db().execute(
        "SELECT * FROM runs WHERE product=? AND set_name=? AND id<? AND status='Completed' AND run_type!='Dry run' "
        "ORDER BY id DESC LIMIT 1", (run["product"], run["set_name"], run["id"])).fetchone()


def _versus(rows, previous, previous_rows):
    """The text for "vs previous official". Runs compare only with the same judge prompt and model (§6.1)."""
    if previous is None:
        return "first run"
    if previous_rows is None:
        return "judge changed"
    if not scoring.summarize(previous_rows)["complete"]:
        return "previous review not finished"
    result = scoring.compare(rows, previous_rows)
    if result is None:
        return "no unchanged cases"
    margin = " within margin" if result["within_margin"] else ""
    return f"{result['diff']:+.1f} pp{margin}"


def _comparable_rows(run, previous):
    if previous is None or previous["judge_prompt"] != run["judge_prompt"]:
        return None
    return load_rows(previous["id"])


def _is_blind(run, rows):
    """Baseline: until Independent 50 is finished the judge's verdicts stay hidden (§5.4)."""
    return any(row["sample"] == "independent" and row["review"] is None for row in rows)
