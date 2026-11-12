"""AI team's runner for Practice and Quick checks, outside the portal (handbook §1.1, §7.1).

    python scripts/practice_run.py "ChatHRMS eval set - practice.xlsx" [--set "Quick checks"] [--out results.csv]

It reads only the practice file and never opens the portal's database, which holds the Exam. A file with an Exam row is refused.
Judge settings come from JUDGE_ENDPOINT, JUDGE_API_KEY, JUDGE_MODEL and optional JUDGE_EFFORT; without them it uses the mock judge.
Exit code: 0 every Quick check passed, 1 a Quick check failed, 2 it could not run. Practice cases may fail (§1.2).
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evalportal import judgeconfig  # noqa: E402
from evalportal.evalset import PRACTICE_FILE_SETS, read_workbook  # noqa: E402
from evalportal.judge import RouterJudge  # noqa: E402
from evalportal.mocks import MockChat, MockJudge  # noqa: E402
from evalportal.runner import RunStopped, call_case, score_case  # noqa: E402

PRODUCT = "ChatHRMS"
QUICK = "Quick checks"
JUDGED_METRICS = ("Behavior", "Key facts", "Groundedness")


def make_judge(env):
    if not env.get("JUDGE_ENDPOINT"):
        print("Mock judge: verdicts are not real. Set JUDGE_ENDPOINT, JUDGE_API_KEY and JUDGE_MODEL for the real one.", file=sys.stderr)
        return MockJudge()
    settings, key, error = judgeconfig.clean({"endpoint": env["JUDGE_ENDPOINT"], "model": env.get("JUDGE_MODEL", ""),
                                              "reasoning_effort": env.get("JUDGE_EFFORT", ""), "api_key": env.get("JUDGE_API_KEY", "")}, None)
    if error:
        raise RunStopped(error)
    return RouterJudge(settings, key)


def run_case(chat, judge, product, case):
    call = call_case(chat, judge, product, case)
    score = score_case(judge, product, case, call)
    # §1.2: a Quick check the judge failed runs once more, because a smoke set at 100% must not hang on one odd verdict.
    judge_failed = any(not score["metrics"][name]["pass"] for name in JUDGED_METRICS if name in score["metrics"])
    if case["set"] == QUICK and judge_failed:
        call = call_case(chat, judge, product, case)
        score = score_case(judge, product, case, call)
    return call, score


def main(argv=None, env=os.environ, chat=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--set", choices=PRACTICE_FILE_SETS, help="Run one set. Default: every row in the file.")
    parser.add_argument("--out", type=Path, help="Write one CSV row per case.")
    args = parser.parse_args(argv)

    try:
        with args.file.open("rb") as file:
            cases, errors = read_workbook(file, PRODUCT, sets=PRACTICE_FILE_SETS)
    except OSError as error:
        print(f"Cannot read the file: {error.strerror}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f'Row {error["row"]} {error["id"]} {error["column"]}: {error["error"]}', file=sys.stderr)
        return 2
    cases = [case for case in cases if not args.set or case["set"] == args.set]
    if not cases:  # exit 0 here would read as "Quick checks passed" with nothing checked
        print(f"The file has no {args.set} cases.", file=sys.stderr)
        return 2
    # shortcut: only MockChat for now, so results only exercise the runner; pass ChatHRMSChat here to run against the real bot.
    if chat is None:
        print("Mock chatbot: answers are not real, so a pass here says nothing about a build.", file=sys.stderr)
        chat = MockChat()

    rows = []
    try:
        judge = make_judge(env)
        build = chat.current_build(PRODUCT)
        for number, case in enumerate(cases, start=1):
            call, score = run_case(chat, judge, PRODUCT, case)
            failed = {name: metric["reason"] for name, metric in score["metrics"].items() if not metric["pass"]}
            rows.append({"id": case["id"], "set": case["set"], "result": "Pass" if score["judge_pass"] else "Fail",
                         "failed_metrics": ", ".join(failed), "reasons": " ".join(failed.values()),
                         "failed_rules": ", ".join(name for name, passed in score["rules"].items() if passed is False),
                         "answer": call["scored"]["text"] if call["scored"] else ""})
            print(f"{number}/{len(cases)} {case['id']} {rows[-1]['result']}", file=sys.stderr)
    except RunStopped as stop:
        print(f"Stopped after {len(rows)} of {len(cases)} cases: {stop}", file=sys.stderr)
        return 2

    if args.out:
        with args.out.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, ("id", "set", "result", "failed_metrics", "reasons", "failed_rules", "answer"))
            writer.writeheader()
            writer.writerows(rows)
    print(f"Build {build} · judge {judge.prompt_version}")
    for name in PRACTICE_FILE_SETS:
        chosen = [row for row in rows if row["set"] == name]
        if chosen:
            print(f"{name}: {sum(row['result'] == 'Pass' for row in chosen)}/{len(chosen)} Pass, "
                  f"{sum(bool(row['failed_rules']) for row in chosen)} with a rule failed")
    for row in rows:
        if row["result"] == "Fail":
            print(f"FAIL {row['id']} [{row['failed_metrics']}] {row['reasons']}")
    if hasattr(judge, "usage"):
        usage = judge.usage
        print(f"{usage['judge_calls']} judge calls, {usage['prompt_tokens']:,} tokens in, {usage['completion_tokens']:,} out, "
              f"answered by {', '.join(usage['models']) or 'an unnamed model'}")
    return 1 if any(row["set"] == QUICK and row["result"] == "Fail" for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
