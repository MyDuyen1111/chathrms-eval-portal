"""Read an exam eval set workbook and report errors by case id (handbook §1.5, §2.2)."""
import hashlib
import json
import re

from openpyxl import load_workbook

from .scoring import BEHAVIORS, FROM_DOCS

COMMON = ["id", "question", "topic_group", "expected_behavior", "key_facts",
          "source_document", "location", "set", "approved_by"]
# `user` is the ChatHRMS employee code that signs in and asks the question.
BY_PRODUCT = {"ChatHRMS": ["user"]}
# Practice and Quick checks stay in the practice file, which is never uploaded.
EXAM_FILE_SETS = ("Exam", "Add-on", "Safety")
PRACTICE_FILE_SETS = ("Practice", "Quick checks")
MAX_ROWS = 5000
# The sheet column is "category". Cases keep the key topic_group, so saved versions and their content hashes stay valid.
# A topic_group header is still read: handbook §1.5 and files already written use that name.
SHEET_NAMES = {"topic_group": "category"}
STORED_KEYS = {"category": "topic_group"}


def _text(value):
    return "" if value is None else str(value).strip()


def parse_key_facts(text):
    """Split the numbered key_facts cell into one string per fact."""
    facts = [re.sub(r"^\s*\d+[.)]\s*", "", line).strip() for line in text.splitlines()]
    return [fact for fact in facts if fact]


def split_documents(text):
    # A case that needs two documents lists them in order, separated by ";".
    return [doc.strip() for doc in text.split(";") if doc.strip()]


def content_hash(case):
    """Same hash across versions means the case did not change, so two runs can compare it."""
    fields = {k: v for k, v in case.items() if k != "approved_by"}
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def _row_errors(case, sets):
    errors = []
    def bad(column, message):
        errors.append((column, message))

    if not case["question"]:
        bad("question", "Cell is empty.")
    if not case["topic_group"]:
        bad("topic_group", "Cell is empty.")
    if not case["approved_by"] and case["set"] != "Practice":  # §1.5: AI team and BA add Practice cases at any time
        bad("approved_by", "Cell is empty.")
    if case["set"] not in sets:
        bad("set", f'"{case["set"]}" is not an allowed value. Use {", ".join(sets)}.')
    behavior = case["expected_behavior"]
    if behavior not in BEHAVIORS:
        bad("expected_behavior", f'"{behavior}" is not an allowed value.')
    elif behavior in FROM_DOCS:
        for column in ("key_facts", "source_document", "location"):
            if not case[column]:
                bad(column, f'Required for expected_behavior "{behavior}". Cell is empty.')
    if not case["user"]:
        bad("user", "Cell is empty.")
    return errors


def read_workbook(file, product, sets=EXAM_FILE_SETS):
    """Return (cases, errors). Any error means the caller must save nothing."""
    try:
        book = load_workbook(file, read_only=True, data_only=True)
    except Exception:
        return [], [{"row": "", "id": "", "column": "", "error": "The file is not a readable .xlsx workbook."}]
    try:
        if "Cases" not in book.sheetnames:
            return [], [{"row": "", "id": "", "column": "", "error": 'The workbook has no sheet named "Cases".'}]
        rows = book["Cases"].iter_rows(values_only=True)
        header = [STORED_KEYS.get(_text(cell), _text(cell)) for cell in next(rows, ())]
        required = COMMON + BY_PRODUCT[product]
        missing = [column for column in required if column not in header]
        if missing:
            return [], [{"row": 1, "id": "", "column": SHEET_NAMES.get(column, column), "error": "Column is missing or misnamed."}
                        for column in missing]

        cases, errors, seen = [], [], set()
        for number, cells in enumerate(rows, start=2):
            if number > MAX_ROWS:
                errors.append({"row": number, "id": "", "column": "", "error": f"The file is over {MAX_ROWS} rows."})
                break
            values = dict(zip(header, map(_text, cells)))
            if not any(values.values()):
                continue
            case = {column: values.get(column, "") for column in required}
            case["leak_strings"] = values.get("leak_strings", "")  # Safety only, optional
            case_id = case["id"]
            found = _row_errors(case, sets)
            if not case_id:
                found.append(("id", "Cell is empty."))
            elif case_id in seen:
                found.append(("id", "This id is used twice."))
            seen.add(case_id)
            errors += [{"row": number, "id": case_id, "column": SHEET_NAMES.get(column, column), "error": message}
                       for column, message in found]
            cases.append(case)
        if not cases and not errors:
            errors.append({"row": "", "id": "", "column": "", "error": 'Sheet "Cases" has no rows.'})
        return cases, errors
    finally:
        book.close()
