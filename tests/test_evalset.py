import io
import unittest

from openpyxl import Workbook

from evalportal.evalset import COMMON, content_hash, parse_key_facts, read_workbook, split_documents

GOOD = {"id": "CH-002", "question": "Mỗi tuần tôi được làm việc từ xa mấy ngày?", "topic_group": "Làm việc từ xa",
        "expected_behavior": "Answer with a source", "key_facts": "1. Tối đa 2 ngày mỗi tuần\n2. Đăng ký trên HRMS",
        "source_document": "KB01_HR_Quy dinh lam viec tu xa_01.11.2026", "location": "Điều 2", "set": "Exam",
        "approved_by": "BA, QC, 2026-11-10", "user": "NV002"}


def workbook(rows, columns=None, sheet="Cases"):
    book = Workbook()
    ws = book.active
    ws.title = sheet
    columns = columns or list(GOOD)
    ws.append(columns)
    for row in rows:
        ws.append([row.get(column) for column in columns])
    out = io.BytesIO()
    book.save(out)
    out.seek(0)
    return out


class ReadWorkbook(unittest.TestCase):
    def test_good_file_passes(self):
        cases, errors = read_workbook(workbook([GOOD]), "ChatHRMS")
        self.assertEqual(errors, [])
        self.assertEqual(cases[0]["id"], "CH-002")

    def test_the_two_errors_in_the_handbook_mockup(self):
        rows = [GOOD | {"id": "CH-031", "key_facts": None},
                GOOD | {"id": "CH-077", "expected_behavior": "Answer w/ source"}]
        _, errors = read_workbook(workbook(rows), "ChatHRMS")
        self.assertEqual([(e["row"], e["id"], e["column"]) for e in errors],
                         [(2, "CH-031", "key_facts"), (3, "CH-077", "expected_behavior")])
        self.assertIn('Required for expected_behavior "Answer with a source"', errors[0]["error"])
        self.assertIn('"Answer w/ source" is not an allowed value', errors[1]["error"])

    def test_misnamed_column_is_reported(self):
        columns = [c if c != "key_facts" else "keyfacts" for c in GOOD]
        _, errors = read_workbook(workbook([], columns), "ChatHRMS")
        self.assertEqual(errors[0]["column"], "key_facts")

    def test_category_column_and_its_old_name(self):
        renamed = [("category" if c == "topic_group" else c) for c in GOOD]
        row = GOOD | {"category": "Làm việc từ xa"}
        for columns in (renamed, list(GOOD)):
            cases, errors = read_workbook(workbook([row], columns), "ChatHRMS")
            self.assertEqual((errors, cases[0]["topic_group"]), ([], "Làm việc từ xa"))
        _, errors = read_workbook(workbook([], [c for c in GOOD if c != "topic_group"]), "ChatHRMS")
        self.assertEqual(errors[0]["column"], "category")
        _, errors = read_workbook(workbook([row | {"category": ""}], renamed), "ChatHRMS")
        self.assertEqual(errors[0]["column"], "category")

    def test_practice_is_not_allowed_in_the_exam_file(self):
        _, errors = read_workbook(workbook([GOOD | {"set": "Practice"}]), "ChatHRMS")
        self.assertEqual(errors[0]["column"], "set")

    def test_duplicate_id(self):
        _, errors = read_workbook(workbook([GOOD, GOOD]), "ChatHRMS")
        self.assertEqual(errors[0]["error"], "This id is used twice.")

    def test_refuse_needs_no_key_facts_or_document(self):
        row = GOOD | {"expected_behavior": "Refuse", "key_facts": None, "source_document": None, "location": None}
        self.assertEqual(read_workbook(workbook([row]), "ChatHRMS")[1], [])

    def test_user_is_required(self):
        _, errors = read_workbook(workbook([GOOD | {"user": None}]), "ChatHRMS")
        self.assertEqual([(e["id"], e["column"]) for e in errors], [("CH-002", "user")])
        _, errors = read_workbook(workbook([], COMMON), "ChatHRMS")
        self.assertEqual([e["column"] for e in errors], ["user"])

    def test_blank_rows_are_skipped(self):
        cases, errors = read_workbook(workbook([GOOD, {}]), "ChatHRMS")
        self.assertEqual((len(cases), errors), (1, []))

    def test_numeric_cell_becomes_text(self):
        cases, _ = read_workbook(workbook([GOOD | {"user": 1001}]), "ChatHRMS")
        self.assertEqual(cases[0]["user"], "1001")

    def test_not_a_workbook(self):
        _, errors = read_workbook(io.BytesIO(b"not a zip"), "ChatHRMS")
        self.assertIn("not a readable", errors[0]["error"])

    def test_missing_sheet(self):
        _, errors = read_workbook(workbook([GOOD], sheet="Other"), "ChatHRMS")
        self.assertIn("Cases", errors[0]["error"])


class Helpers(unittest.TestCase):
    def test_key_facts(self):
        self.assertEqual(parse_key_facts("1. One\n2) Two\n\nThree"), ["One", "Two", "Three"])

    def test_documents(self):
        self.assertEqual(split_documents("A; B"), ["A", "B"])
        self.assertEqual(split_documents(""), [])

    def test_hash_ignores_approval_only(self):
        self.assertEqual(content_hash(GOOD), content_hash(GOOD | {"approved_by": "QC"}))
        self.assertNotEqual(content_hash(GOOD), content_hash(GOOD | {"key_facts": "1. Other"}))


if __name__ == "__main__":
    unittest.main()
