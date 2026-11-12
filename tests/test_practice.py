"""The AI team's runner for the practice file."""
import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from evalportal.evalset import PRACTICE_FILE_SETS, read_workbook
from evalportal.mocks import MockChat, MockJudge
from evalportal.scoring import REFUSE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import practice_run  # noqa: E402

COLUMNS = ["id", "set", "user", "question", "topic_group", "expected_behavior", "key_facts", "source_document", "location", "approved_by"]


def row(case_id, set_name="Quick checks", approved_by="QC"):
    return [case_id, set_name, "NV001", f"Can you do {case_id}?", "Nghỉ phép", REFUSE, "", "", "", approved_by]


class FailsTheFirstTime(MockJudge):
    def __init__(self, failures):
        self.failures = failures
        self.asked = 0

    def behavior(self, case, scored):
        self.asked += 1
        if self.asked <= self.failures:
            return {"pass": False, "reason": "Wrong."}
        return {"pass": True, "reason": ""}


class PracticeRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def workbook(self, *rows):
        book = Workbook()
        sheet = book.active
        sheet.title = "Cases"
        sheet.append(COLUMNS)
        for item in rows:
            sheet.append(item)
        path = self.folder / "practice.xlsx"
        book.save(path)
        return path

    def run_it(self, path, *args, judge=None):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), patch.object(practice_run, "make_judge", lambda env: judge or MockJudge()):
            code = practice_run.main([str(path), *args], env={}, chat=MockChat())
        return code, out.getvalue(), err.getvalue()

    def test_every_quick_check_passing_gives_exit_0_and_a_csv(self):
        out_file = self.folder / "results.csv"
        code, out, _ = self.run_it(self.workbook(row("QC-1"), row("QC-2")), "--out", str(out_file))
        self.assertEqual(code, 0)
        self.assertIn("Quick checks: 2/2 Pass", out)
        with out_file.open(encoding="utf-8-sig") as file:
            self.assertEqual([item["result"] for item in csv.DictReader(file)], ["Pass", "Pass"])

    def test_a_judged_failure_reruns_once_and_the_second_result_stands(self):
        judge = FailsTheFirstTime(1)
        code, out, _ = self.run_it(self.workbook(row("QC-1")), judge=judge)
        self.assertEqual((code, judge.asked), (0, 2))
        self.assertIn("1/1 Pass", out)

    def test_failing_twice_gives_exit_1_and_names_the_case(self):
        code, out, _ = self.run_it(self.workbook(row("QC-1")), judge=FailsTheFirstTime(2))
        self.assertEqual(code, 1)
        self.assertIn("FAIL QC-1 [Behavior] Wrong.", out)

    def test_practice_may_fail_and_does_not_rerun(self):
        judge = FailsTheFirstTime(1)
        code, out, _ = self.run_it(self.workbook(row("P-1", "Practice", "")), judge=judge)
        self.assertEqual((code, judge.asked), (0, 1))
        self.assertIn("Practice: 0/1 Pass", out)

    def test_one_set_can_run_alone(self):
        _, out, _ = self.run_it(self.workbook(row("QC-1"), row("P-1", "Practice")), "--set", "Practice")
        self.assertIn("Practice: 1/1 Pass", out)
        self.assertNotIn("Quick checks:", out)

    def test_an_exam_row_is_refused_before_any_call(self):
        judge = FailsTheFirstTime(0)
        code, _, err = self.run_it(self.workbook(row("QC-1"), row("CH-014", "Exam")), judge=judge)
        self.assertEqual((code, judge.asked), (2, 0))
        self.assertIn('"Exam" is not an allowed value', err)

    def test_nothing_to_check_is_never_a_pass(self):
        code, _, err = self.run_it(self.workbook(row("P-1", "Practice")), "--set", "Quick checks")
        self.assertEqual(code, 2)
        self.assertIn("no Quick checks cases", err)
        code, _, err = self.run_it(self.folder / "missing.xlsx")
        self.assertEqual(code, 2)
        self.assertIn("Cannot read the file", err)

    def test_a_stopped_chatbot_gives_exit_2(self):
        path = self.workbook(row("QC-1"))
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err), patch.object(practice_run, "make_judge", lambda env: MockJudge()):
            code = practice_run.main([str(path)], env={}, chat=MockChat(fail_case="QC-1"))
        self.assertEqual(code, 2)
        self.assertIn("Stopped after 0 of 1 cases", err.getvalue())

    def test_bad_judge_settings_stop_before_any_case(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = practice_run.main([str(self.workbook(row("QC-1")))],
                                     env={"JUDGE_ENDPOINT": "http://8.8.8.8/v1", "JUDGE_MODEL": "m", "JUDGE_API_KEY": "k"}, chat=MockChat())
        self.assertEqual(code, 2)
        self.assertIn("must start with https://", err.getvalue())


class PracticeFile(unittest.TestCase):
    def test_quick_checks_need_approval_but_practice_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            book = Workbook()
            sheet = book.active
            sheet.title = "Cases"
            sheet.append(COLUMNS)
            sheet.append(row("P-1", "Practice", ""))
            sheet.append(row("QC-1", "Quick checks", ""))
            path = Path(folder) / "p.xlsx"
            book.save(path)
            with path.open("rb") as file:
                _, errors = read_workbook(file, "ChatHRMS", sets=PRACTICE_FILE_SETS)
        self.assertEqual([(error["id"], error["column"]) for error in errors], [("QC-1", "approved_by")])
