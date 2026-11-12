"""Runs: the list, New run, the run page with its Summary and Report tabs, and the Fail list export."""
import io
import json
from collections import defaultdict

from flask import abort, current_app, g, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook

from .. import runner, scoring
from ..evalset import EXAM_FILE_SETS
from ..i18n import t
from .common import _current_judge, _stamp, bp, get_db, needs_role, products
from .evalsets import _product_arg, _versions
from .results import _comparable_rows, _is_blind, _previous_official, _versus, load_rows
from .review import _review_context

MILESTONES = {"Baseline": "Baseline", "M1 gate": "M1", "UAT entry": "UAT", "Final run": "Final"}
SET_TAGS = {"Exam": "exam", "Add-on": "addon", "Safety": "safety"}
RUN_TYPES = ("Official", "Dry run", "Rerun after fix")


@bp.route("/runs")
def runs():
    product = request.args.get("product", "")
    set_name = request.args.get("set", "")
    version = request.args.get("version", "")
    query, params = "SELECT * FROM runs WHERE 1=1", []
    for column, value in (("product", product), ("set_name", set_name), ("version_label", version)):
        if value:
            query += f" AND {column}=?"
            params.append(value)
    listed = []
    for run in get_db().execute(query + " ORDER BY id DESC", params).fetchall():
        entry = {**dict(run), "judge": None, "after": None, "versus": "—", "review": "—"}
        if run["status"] == "Completed":
            rows = load_rows(run["id"])
            summary = scoring.summarize(rows)
            entry["judge"] = summary["judge"]
            if run["run_type"] != "Dry run":
                entry["review"] = "Done" if summary["complete"] else f"{summary['reviewed']} / {summary['need']}"
                if summary["complete"]:
                    entry["after"] = summary["acceptance"]
                    previous = _previous_official(run)
                    entry["versus"] = _versus(rows, previous, _comparable_rows(run, previous))
        listed.append(entry)
    labels = [r[0] for r in get_db().execute("SELECT DISTINCT label FROM versions WHERE label IS NOT NULL ORDER BY label")]
    return render_template("runs.html", runs=listed, products=products(), sets=EXAM_FILE_SETS, labels=labels,
                           product=product, set_name=set_name, version=version)


def _run_name(conn, product, set_name, milestone, label, build, run_type):
    tag = MILESTONES[milestone] if run_type != "Dry run" else "dry"
    base = f"{product}-{SET_TAGS[set_name]}-{tag}-{label}-{build}"
    taken = {row[0] for row in conn.execute("SELECT name FROM runs WHERE name LIKE ?", (base + "%",))}
    if run_type != "Rerun after fix" and base not in taken:
        return base
    number = 2
    while f"{base}-r{number}" in taken:
        number += 1
    return f"{base}-r{number}"


@bp.route("/runs/new", methods=["GET", "POST"])
@needs_role("QC")
def new_run():
    conn = get_db()
    product = request.form.get("product") or _product_arg()
    if product not in products():
        abort(404)
    chat, judge = current_app.config["CHAT"], _current_judge()
    build = chat.current_build(product)
    form, error = request.form, None
    if request.method == "POST":
        set_name, run_type = form.get("set"), form.get("run_type")
        milestone = form.get("milestone") or None
        version = conn.execute("SELECT * FROM versions WHERE id=? AND product=? AND status='Locked'",
                               (form.get("version"), product)).fetchone()
        dry = run_type == "Dry run"
        if set_name not in EXAM_FILE_SETS or run_type not in RUN_TYPES:
            error = t("Choose a set and a run type.")
        elif version is None:
            error = t("Choose a locked version.")
        elif not dry and milestone not in MILESTONES:
            error = t("Choose a milestone.")
        elif not dry and form.get("quick_checks") != "on":
            error = t("Official runs need the AI team's confirmation that Quick checks passed 100% on this build.")
        elif not conn.execute("SELECT 1 FROM cases WHERE version_id=? AND set_name=?", (version["id"], set_name)).fetchone():
            error = t("This version has no {set_name} cases.", set_name=set_name)
        elif conn.execute("SELECT 1 FROM runs WHERE product=? AND status='Running'", (product,)).fetchone():
            error = t("A {product} run is still running. Start this one when it finishes.", product=product)
        else:
            label = version["label"]
            milestone = None if dry else milestone
            name = _run_name(conn, product, set_name, milestone, label, form.get("build", ""), run_type)
            with conn:
                run_id = conn.execute(
                    "INSERT INTO runs(name, product, set_name, version_id, version_label, build, milestone, run_type,"
                    " judge_prompt, started_by, started_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (name, product, set_name, version["id"], label, form.get("build", ""), milestone, run_type,
                     judge.prompt_version, g.user["name"], _stamp())).lastrowid
            runner.start(current_app._get_current_object(), run_id, judge)
            return redirect(url_for("portal.run_page", run_id=run_id))
    versions = [v for v in _versions(product) if v["status"] == "Locked"]  # §4.3: the list shows locked versions only
    return render_template("new_run.html", product=product, products=products(), sets=EXAM_FILE_SETS,
                           set_tags=SET_TAGS, versions=versions, build=build, milestones=MILESTONES, run_types=RUN_TYPES,
                           chosen_version=form.get("version") or (versions and str(versions[0]["id"])), error=error, form=form,
                           judge=judge)


def _steps(run):
    steps = []
    for index, name in enumerate(runner.STEPS):
        state = "done" if run["status"] == "Completed" or index < run["step"] else ""
        if index == run["step"] and run["status"] != "Completed":
            state = "err" if run["status"] == "Failed" else "now"
        counted = ""
        if name in ("Call chatbot", "Judge") and run["total"]:
            if state == "done":
                counted = f" {run['total']}/{run['total']}"
            elif state == "now":
                counted = f" {run['done']}/{run['total']}"
            elif state == "err":
                counted = f" {max(run['done'] - 1, 0)}/{run['total']}"
        steps.append({"name": name + counted, "state": state})
    return steps


def _failure_head(run, say=str.format):
    """English by default for the copy text the AI team gets; say=t for the page."""
    step = runner.STEPS[run["step"]]
    if step in ("Call chatbot", "Judge") and run["done"]:
        return say("{step} failed at case {done} of {total}.", step=step, done=run["done"], total=run["total"])
    return say("{step} failed.", step=step)


@bp.route("/runs/<int:run_id>")
def run_page(run_id):
    run = get_db().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone() or abort(404)
    tab = request.args.get("tab", "summary")
    if tab not in ("summary", "report", "review"):
        abort(404)
    context = {"run": run, "tab": tab, "steps": _steps(run), "failure": None, "copy_text": None,
               "telemetry": json.loads(run["telemetry"] or "{}")}
    if run["status"] == "Failed":
        context["failure"] = _failure_head(run, t)
        context["copy_text"] = f"Run: {run['name']}\n{_failure_head(run)} {run['error']}"
    if run["status"] == "Completed":
        rows = load_rows(run_id)
        previous = _previous_official(run) if run["run_type"] != "Dry run" else None
        previous_rows = _comparable_rows(run, previous)
        context.update(rows=rows, summary=scoring.summarize(rows), blind=_is_blind(run, rows),
                       is_dry=run["run_type"] == "Dry run", is_safety=run["set_name"] == "Safety",
                       baseline=any(r["sample"] == "independent" for r in rows))
        if tab == "summary":
            context.update(_summary_context(run, rows, previous, previous_rows, context["summary"]))
        elif tab == "report":
            context.update(_report_context(rows))
        else:
            context.update(_review_context(run, rows, previous_rows, context["blind"]))
    return render_template("run.html", **context)


def _groups(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["topic_group"]].append(row)
    return groups


def _summary_context(run, rows, previous, previous_rows, summary):
    before = _groups(previous_rows or [])
    topics = []
    for name, group in _groups(rows).items():
        judge = (sum(row["judge_pass"] for row in group), len(group))
        versus = "—"
        if previous is not None and summary["complete"] and name in before:
            versus = _versus(group, previous, before[name])
        topics.append({"name": name, "cases": len(group), "judge": judge, "versus": versus})
    counts = ", ".join(f"{name}: {n}" for name, n in summary["failure_counts"].items() if n) or "No bot failures"
    targets = scoring.targets(summary, run["milestone"]) if summary["complete"] and run["set_name"] == "Exam" else {}
    return {"topics": topics, "has_previous": previous is not None, "targets": targets,
            "rules_missed": sum(bool(targets.get(name)) and not targets[name]["met"] for name in scoring.RULES),
            "ai_team_text": f"{counts}. Wrong location: {summary['wrong_location']}."}


def _report_context(rows):
    groups = []
    for name, group in _groups(rows).items():
        groups.append({"name": name, "rows": group, "passed": (sum(r["judge_pass"] for r in group), len(group))})
    return {"groups": groups, "open_case": request.args.get("case"), "back_chip": request.args.get("chip"), "rule_names": scoring.RULES}


def _text_cell(ws, row, column, value):
    # Forced to text: a question like "=HYPERLINK(...)" must stay a string when Foundation opens the file.
    cell = ws.cell(row=row, column=column)
    cell.value = value
    cell.data_type = "s"


@bp.route("/runs/<int:run_id>/fail-list.xlsx")
@needs_role("QC")
def fail_list(run_id):
    run = get_db().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone() or abort(404)
    if run["status"] != "Completed" or not run["milestone"]:
        abort(409, t("Only a completed run with a milestone has a fail list."))
    rows = load_rows(run_id)
    if not scoring.summarize(rows)["complete"]:
        abort(409, t("Finish the review first."))
    book = Workbook()
    ws = book.active
    ws.title = "Fail list"
    ws.append(["id", "question", "failure type", "reason"])
    line = 1
    for row in rows:
        if scoring.final_pass(row):
            continue
        line += 1
        review = row["review"] or {}
        reasons = [m["reason"] for m in row["metrics"].values() if not m["pass"] and m["reason"]]
        failure = review.get("failure_type") or (f"Owner: {review['owner']}" if review.get("owner") else "")
        for column, value in enumerate((row["case_id"], row["question"], failure,
                                        " ".join(reasons) or review.get("note", "")), start=1):
            _text_cell(ws, line, column, value)
    out = io.BytesIO()
    book.save(out)
    out.seek(0)
    return send_file(out, as_attachment=True, download_name=f"{run['name']}-fail-list.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
