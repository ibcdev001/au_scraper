"""Fail the build when the crawl came back short.

Scrapy writes its feed as it goes, so an interrupted or partly failed crawl
leaves a valid JSON file holding a fraction of the register. Publishing that
would silently drop approvals from the lookup page, which is worse than
publishing nothing: an inspector would read "no model report" for a vehicle
that has one. This checks the counts before the page is built.

Run:  python scripts/check_fresh.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COVERAGE = ROOT / "output" / "coverage.json"

# Register sizes observed 2026-10-13. A real register only grows, so anything
# materially below this means the crawl, not the department, lost records.
FLOOR = {"sev_list": 584, "sev_details": 584, "mre_list": 926, "mre_details": 926}
TOLERANCE = 0.95


def main():
    if not COVERAGE.exists():
        sys.exit(f"missing {COVERAGE} - run `python -m rover.pair` first")
    cover = json.loads(COVERAGE.read_text(encoding="utf-8"))
    counts = cover["_meta"]["row_counts"]
    summary = cover["summary"]

    problems = []
    for key, floor in FLOOR.items():
        got = counts.get(key, 0)
        if got < floor * TOLERANCE:
            problems.append(
                f"{key}: {got} rows, expected at least {int(floor * TOLERANCE)} "
                f"(baseline {floor})"
            )
    if counts.get("sev_details", 0) != counts.get("sev_list", 0):
        problems.append("sev: detail pages do not match list rows")
    if counts.get("mre_details", 0) != counts.get("mre_list", 0):
        problems.append("mre: detail pages do not match list rows")
    problems.extend(summary.get("data_warnings", []))

    if problems:
        print("refusing to publish - the crawl looks incomplete:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print(
        "crawl looks complete: "
        f"{counts['sev_details']} SEV approvals, {counts['mre_details']} model "
        f"reports, {summary['pairs']} pairs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
