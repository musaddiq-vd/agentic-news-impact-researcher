"""Run the eval questions on REAL Tavily + Bedrock and catch quality regressions.

    python -m evals.run                       # all cases, compare with the last saved run
    python -m evals.run --only coal-cost,almm # a few cases
    python -m evals.run --baseline evals/results/2026-11-03_0800.json
    python -m evals.run --min-score 0.9       # exit 1 if the average score is lower

Costs real API calls (about 13 runs). Nothing is saved to the app's DB.
Results go to evals/results/<date_time>.json; the newest earlier file is the default baseline.
A regression is a case that passed every check last time and fails one now.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from app.config import IST, get_settings
from app.graph import run_graph
from evals.checks import Check, check_run, score

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"
RESULTS = HERE / "results"


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def load_cases(only: str | None = None) -> list[dict]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if only:
        wanted = {x.strip() for x in only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def run_case(case: dict, runner=run_graph, today=None) -> dict:
    today = today or datetime.now(IST).date()
    start = time.monotonic()
    try:
        result = runner(case["question"], case["topic"])
        checks = check_run(case, result, today, get_settings().days)
        status, cards = result["status"], len(result["cards"])
    except Exception as exc:  # a crash is a failed case, not a crashed eval
        checks = [Check("no_crash", False, f"{type(exc).__name__}: {exc}"[:200])]
        status, cards = "crash", 0
    return {
        "id": case["id"], "status": status, "cards": cards,
        "seconds": round(time.monotonic() - start, 1),
        "score": round(score(checks), 3),
        "checks": [{"name": c.name, "passed": c.passed, "detail": "" if c.passed else c.detail} for c in checks],
    }


def latest_baseline(exclude: Path | None = None) -> Path | None:
    files = sorted(p for p in RESULTS.glob("*.json") if p != exclude)
    return files[-1] if files else None


def regressions(now: list[dict], before: dict) -> list[str]:
    old = {r["id"]: r for r in before.get("cases", [])}
    out = []
    for r in now:
        prev = old.get(r["id"])
        if prev and prev["score"] == 1.0 and r["score"] < 1.0:
            failed = [c["name"] for c in r["checks"] if not c["passed"]]
            out.append(f"{r['id']}: passed before, now fails {failed}")
    return out


def print_report(rows: list[dict], avg: float) -> None:
    print()
    print(_c("1", f"{'case':<20} {'status':<9} {'cards':>5} {'checks':>8} {'time':>7}"))
    for r in rows:
        passed = sum(c["passed"] for c in r["checks"])
        mark = _c("92", "✔") if r["score"] == 1.0 else _c("91", "✖")
        print(f"{r['id']:<20} {r['status']:<9} {r['cards']:>5} {passed:>4}/{len(r['checks']):<2} {mark} {r['seconds']:>5.1f}s")
    fails = [(r["id"], c) for r in rows for c in r["checks"] if not c["passed"]]
    if fails:
        print(_c("1", "\nFailed checks"))
        for cid, c in fails:
            print(f"  {_c('91', '✖')} {cid} · {c['name']}: {c['detail']}")
    color = "92" if avg >= 0.9 else "93" if avg >= 0.75 else "91"
    print(_c("1", "\nScore: ") + _c(color + ";1", f"{avg:.0%}") + f"  ({sum(r['score'] == 1.0 for r in rows)}/{len(rows)} cases fully pass)")


def main(argv: list[str] | None = None, runner=run_graph) -> int:
    parser = argparse.ArgumentParser(description="Real-data quality eval (uses Tavily and Bedrock).")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--baseline", help="results file to compare with (default: the newest one)")
    parser.add_argument("--min-score", type=float, default=0.0, help="fail if the average score is lower")
    args = parser.parse_args(argv)

    os.environ.setdefault("TRACE_LOGS", "0")  # keep the report readable; agent lines are noise here
    cases = load_cases(args.only)
    if not cases:
        print("No cases match --only.", file=sys.stderr)
        return 2

    rows = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']}: {case['question']}", flush=True)
        rows.append(run_case(case, runner))
    avg = sum(r["score"] for r in rows) / len(rows)
    print_report(rows, avg)

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(IST):%Y-%m-%d_%H%M%S}.json"
    baseline = Path(args.baseline) if args.baseline else latest_baseline(exclude=out)
    out.write_text(json.dumps({"created_at": datetime.now(IST).isoformat(timespec="seconds"),
                               "score": round(avg, 3), "cases": rows}, indent=2), encoding="utf-8")
    print(f"Saved: {out}")

    regressed = []
    if baseline and baseline.exists():
        before = json.loads(baseline.read_text(encoding="utf-8"))
        regressed = regressions(rows, before)
        print(f"Baseline: {baseline.name} (score {before.get('score', 0):.0%})")
        for line in regressed:
            print(f"  {_c('91', 'REGRESSION')} {line}")
        if not regressed:
            print(f"  {_c('92', 'No regressions.')}")
    return 1 if regressed or avg < args.min_score else 0


if __name__ == "__main__":
    sys.exit(main())
