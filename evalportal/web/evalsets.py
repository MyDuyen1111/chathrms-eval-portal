"""Eval sets: QC uploads a version, BA locks it, everyone can view it."""
import json

from flask import abort, g, redirect, render_template, request, url_for

from ..evalset import BY_PRODUCT, SHEET_NAMES, content_hash, read_workbook
from ..i18n import t
from .common import _stamp, bp, get_db, needs_role, products


def _versions(product):
    conn = get_db()
    rows = conn.execute("SELECT * FROM versions WHERE product=? AND status!='Replaced' ORDER BY id DESC", (product,)).fetchall()
    versions = []
    for row in rows:
        counts = conn.execute("SELECT set_name, COUNT(*) AS n FROM cases WHERE version_id=? GROUP BY set_name", (row["id"],))
        versions.append({**dict(row), "counts": {c["set_name"]: c["n"] for c in counts}})
    return versions


def _next_label(product):
    locked = get_db().execute("SELECT COUNT(*) FROM versions WHERE product=? AND status='Locked'", (product,)).fetchone()[0]
    return f"gs{locked + 1}"


def _eval_sets_page(product, errors=None, uploaded=None, saved=None, locked=None):
    versions = _versions(product)
    if uploaded is None and versions:
        uploaded = (versions[0]["filename"], versions[0]["uploaded_by"], sum(versions[0]["counts"].values()))
    # §1.4 needs planted strings to check for, but §1.5 has no column for them, so a file can pass with none.
    no_leak = versions and get_db().execute(
        "SELECT COUNT(*) FROM cases WHERE version_id=? AND set_name='Safety' AND json_extract(data, '$.leak_strings')=''",
        (versions[0]["id"],)).fetchone()[0]
    return render_template("eval_sets.html", product=product, products=products(), versions=versions, errors=errors, no_leak=no_leak,
                           uploaded=uploaded, saved=saved, has_draft=any(v["status"] == "Draft" for v in versions),
                           locked=next((v["label"] for v in versions if v["label"] == locked), None),
                           next_label=_next_label(product))


def _product_arg():
    product = request.args.get("product", products()[0])
    if product not in products():
        abort(404)
    return product


@bp.route("/eval-sets")
def eval_sets():
    return _eval_sets_page(_product_arg(), saved=request.args.get("saved"), locked=request.args.get("locked"))


@bp.post("/eval-sets/<product>/upload")
@needs_role("QC")
def upload(product):
    if product not in products():
        abort(404)
    file = request.files.get("file")
    if not file or not file.filename:
        return _eval_sets_page(product, errors=[{"row": "", "id": "", "column": "", "error": t("Choose an .xlsx file first.")}])
    cases, errors = read_workbook(file.stream, product)
    if errors:
        return _eval_sets_page(product, errors=errors, uploaded=(file.filename, g.user["name"], len(cases)))
    conn = get_db()
    with conn:
        conn.execute("UPDATE versions SET status='Replaced' WHERE product=? AND status='Draft'", (product,))
        version = conn.execute("INSERT INTO versions(product, status, filename, uploaded_by, uploaded_at) VALUES(?,?,?,?,?)",
                               (product, "Draft", file.filename, g.user["name"], _stamp())).lastrowid
        conn.executemany("INSERT INTO cases(version_id, case_id, set_name, data, content_hash) VALUES(?,?,?,?,?)",
                         [(version, c["id"], c["set"], json.dumps(c), content_hash(c)) for c in cases])
    return redirect(url_for("portal.eval_sets", product=product, saved=1))


@bp.post("/eval-sets/version/<int:version_id>/lock")
@needs_role("BA")
def lock(version_id):
    conn = get_db()
    version = conn.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone() or abort(404)
    if version["status"] != "Draft":
        abort(409, t("Only a Draft version can be locked."))
    label = _next_label(version["product"])
    with conn:
        conn.execute("UPDATE versions SET status='Locked', label=?, locked_by=?, locked_at=? WHERE id=?",
                     (label, g.user["name"], _stamp(), version_id))
    return redirect(url_for("portal.eval_sets", product=version["product"], locked=label))


@bp.route("/eval-sets/version/<int:version_id>")
def view_version(version_id):
    conn = get_db()
    version = conn.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone() or abort(404)
    # shortcut: shows every row with no paging; real sets are about 140 rows, add paging if one reaches the thousands.
    cases = [json.loads(row["data"]) for row in conn.execute("SELECT data FROM cases WHERE version_id=? ORDER BY id", (version_id,))]
    optional = ["kb"] if any(case.get("kb") for case in cases) else []
    columns = ["id", "set", *BY_PRODUCT[version["product"]], *optional, "question", "topic_group", "expected_behavior", "key_facts",
               "source_document", "location", "approved_by", "leak_strings"]
    return render_template("eval_set_view.html", version=version, cases=cases, columns=columns, sheet_names=SHEET_NAMES,
                           next_label=_next_label(version["product"]))
