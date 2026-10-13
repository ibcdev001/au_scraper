"""Build the inspector's lookup page from the paired registers.

Reads output/pairs.json and output/coverage.json, writes a single
self-contained HTML file: search by chassis/model code, VIN, make, model or
approval number, and read the published criteria for whatever comes back.

The page states the criteria and stops there. It computes no eligibility
verdict, and never intersects the SEV and Model Report build-date ranges - the
inspector does that.

Every published record ends up searchable, in one of three shapes:

  * a SEV approval with the Model Reports that cite it underneath - the shape
    of the decision: one import eligibility, the workshops that can comply it;
  * a SEV approval that no Model Report cites, which says so;
  * a Model Report whose SEV approval is missing from the register, or which
    links none at all - published approvals, so they must stay findable.

Run:
    python -m rover.page
    python -m rover.page --out output --html output/rover_lookup.html
"""

import argparse
import json
import pathlib
import sys

from rover import normalize as nz

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

TEMPLATE_PATH = pathlib.Path(__file__).resolve().parent / "lookup_template.html"

# what the page shows for a SEV approval, paired or not
SEV_FIELDS = (
    "approval", "make", "model", "variant", "variant_details",
    "has_restriction_note", "restriction_dates_in_text", "model_code",
    "criterion", "category_label", "build_range_text", "build_from",
    "build_to", "expiry_text", "expiry", "under_review", "url",
)


def load(path):
    if not path.exists():
        sys.exit(f"missing {path}\nrun `python -m rover.pair` first")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def report_view(mre):
    """What the page shows for one Model Report."""
    return {
        "approval": mre["approval"],
        "make": mre["make"],
        "model": mre["model"],
        "build_range_text": mre["build_range_text"],
        "build_from": mre["build_from"],
        "build_to": mre["build_to"],
        "compliance_level": mre["compliance_level"],
        "compliance_notes": mre.get("compliance_notes"),
        "report_notes": mre.get("report_notes"),
        "body_shape": mre.get("body_shape"),
        "status": mre["status"],
        "report_type": mre["report_type"],
        "category": mre["category"],
        "source_market": mre["source_market"],
        "work_instruction_id": mre["work_instruction_id"],
        "typical_vin": mre["typical_vin"],
        "based_on": mre["based_on"],
        "nsw_body_code": mre["nsw_body_code"],
        "scope_version_count": mre["scope_version_count"],
        "holder": mre["holder"],
        "url": mre["url"],
    }


def report_haystack(mre):
    return nz.norm_name(" ".join(
        str(v) for v in (
            mre.get("approval"), mre.get("make"), mre.get("model"),
            mre.get("typical_vin"), mre.get("work_instruction_id"),
            mre.get("holder"),
        ) if v
    ))


def group(pairs, unpaired, unresolved, unlinked):
    """Collapse the join table into one entry per SEV approval, then add the
    records with no counterpart so nothing published is unsearchable."""
    groups = {}
    for pair in pairs:
        sev, mre = pair["sev"], pair["mre"]
        key = sev["approval"] or sev["id"]
        entry = groups.get(key)
        if entry is None:
            entry = groups[key] = {
                "kind": "sev",
                "sev": {k: sev.get(k) for k in SEV_FIELDS},
                "reports": [],
                "codes": sorted(set(sev["model_codes"])),
                "vins": [],
                "patterns": [],
                "haystack": "",
            }
        entry["reports"].append(report_view(mre))
        if mre["typical_vin"]:
            entry["vins"].append(mre["typical_vin"])
        for pattern in pair["search"]["vin_patterns"]:
            if pattern not in entry["patterns"]:
                entry["patterns"].append(pattern)
        entry["haystack"] = " ".join(
            dict.fromkeys((entry["haystack"] + " " + pair["search"]["text"]).split())
        )

    # SEV approvals with nothing to pair, carrying the same criteria a paired
    # one shows, so a search for them is just as informative
    for row in unpaired:
        key = row["approval"]
        if key in groups:
            continue
        groups[key] = {
            "kind": "sev",
            "sev": {k: row.get(k) for k in SEV_FIELDS},
            "reports": [],
            "codes": sorted(set(row.get("model_codes") or [])),
            "vins": [],
            "patterns": [],
            "haystack": nz.norm_name(" ".join(
                str(v) for v in (
                    row.get("approval"), row.get("make"), row.get("model"),
                    row.get("variant"), row.get("model_code"),
                ) if v
            )),
            "no_report": True,
        }

    # Model Reports whose SEV approval is not in the register, or that link
    # none at all: still published approvals, so they stay findable alone
    orphans = {}
    for row in unresolved + unlinked:
        mre = row["mre"]
        key = mre["approval"] or mre["id"]
        entry = orphans.get(key)
        if entry is None:
            entry = orphans[key] = {
                "kind": "report",
                "report": report_view(mre),
                "cited_sev": [],
                "note": row["note"],
                "vins": [mre["typical_vin"]] if mre["typical_vin"] else [],
                "patterns": list(nz.vin_patterns(mre["typical_vin"])),
                "haystack": report_haystack(mre),
            }
        if row.get("sev_text"):
            entry["cited_sev"].append(row["sev_text"])
            entry["haystack"] += " " + nz.norm_name(row["sev_text"])

    entries = sorted(
        groups.values(), key=lambda g: g["sev"]["approval"] or ""
    ) + sorted(
        orphans.values(), key=lambda g: g["report"]["approval"] or ""
    )
    for entry in entries:
        entry["vins"] = sorted(set(entry["vins"]))
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT), help="directory holding pairs.json")
    ap.add_argument("--html", default=None, help="file to write")
    args = ap.parse_args(argv)

    out_dir = pathlib.Path(args.out)
    html_path = pathlib.Path(args.html) if args.html else out_dir / "rover_lookup.html"

    pairs_doc = load(out_dir / "pairs.json")
    cover = load(out_dir / "coverage.json")
    entries = group(
        pairs_doc["pairs"],
        cover["sev_without_model_report"],
        cover["unresolved_sev_links"],
        cover["mre_without_sev_link"],
    )

    payload = {
        "entries": entries,
        "meta": {
            "generated_at": pairs_doc["_meta"]["generated_at"],
            "sources": pairs_doc["_meta"]["sources"],
            "counts": pairs_doc["_meta"]["row_counts"],
            "caveat": pairs_doc["_meta"]["caveat"],
            "summary": cover["summary"],
        },
    }

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    marker = "/*__DATA__*/null"
    if marker not in template:
        sys.exit(f"{TEMPLATE_PATH} has no {marker} placeholder")
    # the JSON is embedded in a <script type="application/json">, so only the
    # closing-tag sequence needs escaping
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html_path.write_text(template.replace(marker, blob), encoding="utf-8")

    sev_entries = [e for e in entries if e["kind"] == "sev"]
    report_entries = [e for e in entries if e["kind"] == "report"]
    print(f"{len(sev_entries)} SEV approvals "
          f"({sum(len(e['reports']) for e in sev_entries)} model reports attached, "
          f"{sum(1 for e in sev_entries if e.get('no_report'))} with none)")
    print(f"{len(report_entries)} model reports listed on their own "
          "(SEV approval missing from the register, or none linked)")
    print(f"wrote {html_path}  ({html_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
