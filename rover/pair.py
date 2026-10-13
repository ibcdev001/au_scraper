"""Pair the SEV and MRE registers into one searchable dataset.

Each register holds half of what an inspector needs. A **SEV** entry says a
variant may be imported, and why (the criterion), for which build dates, and
sometimes narrows that further in free text. A **Model Report** says a
registered workshop can modify that model to comply with the ADRs, for which
build dates, to what level of compliance. The report also publishes its
holder and their contact details.

This module joins them and lays the facts side by side. It deliberately
**does not decide eligibility**: no verdict, no intersecting of build-date
ranges, no pass/fail. The inspector reads the criteria and decides.

The join is published, not guessed: every MRE detail page links the SEV
approval(s) it rests on, so `_links` carries an authoritative edge. It is
many-to-many (one report can cite several SEVs, usually variants of one
vehicle; several workshops can hold reports against one SEV), so the output is
a join table, one row per SEV x MRE pair.

Run after crawling (see README):

    python -m rover.pair

Reads  output/{sev,mre}_{list,details}.json
Writes output/pairs.json and output/coverage.json
"""

import argparse
import collections
import json
import pathlib
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from rover import normalize as nz

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output"

BASE = "https://www.rover.infrastructure.gov.au"
SOURCES = {
    "sev": f"{BASE}/PublishedApprovals/SEVApprovals/",
    "mre": f"{BASE}/PublishedApprovals/MREApprovals/",
}

# Register sizes observed 2026-10-13. Only used to notice a crawl that died
# half way: a truncated feed would otherwise read as a register full of
# unpaired entries. Update them when the registers grow.
REGISTER_FLOOR = {"sev": 584, "mre": 926}

CAVEAT = (
    "Paired from the ROVER published-approvals registers. This is reference "
    "data, not a decision: no eligibility verdict is computed here. It covers "
    "only the SEV + Model Report route, as published; the other RAV entry pathways (25-year/pre-1989 rules, personal "
    "and immigrant imports, full volume type approval, discretionary "
    "approvals) are not in this data, nor is the separate vehicle import "
    "approval step. Build dates, expiries and variant restrictions are "
    "reproduced as published for a human to read."
)


# ---------------------------------------------------------------------- input
def load(name, required=True):
    path = OUT / f"{name}.json"
    if not path.exists():
        if required:
            sys.exit(
                f"missing {path}\n"
                "run the crawls first - see the Pairing section of README.md"
            )
        return []
    with path.open(encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as exc:
            # Scrapy's JSON exporter only closes the array when the spider
            # finishes, so a feed read mid-crawl is genuinely unterminated.
            sys.exit(
                f"{path} is not valid JSON ({exc})\n"
                "if a crawl is still running, wait for it to finish - the feed "
                "exporter closes the JSON array only when the spider closes"
            )


def by_id(rows):
    return {r["_id"]: r for r in rows if r.get("_id")}


def merged(details, list_rows, kind, warnings):
    """Detail pages hold the substance; list rows carry a few fields that never
    appear on the detail page (under-review, compliance level, expiry dates).
    Join them on the record GUID, which is the same on both sides."""
    lists = by_id(list_rows)
    if list_rows and len(details) != len(list_rows):
        warnings.append(
            f"{kind}: {len(details)} detail pages for {len(list_rows)} list rows "
            "- was the crawl interrupted, or run without -a details=1?"
        )
    floor = REGISTER_FLOOR.get(kind)
    if floor and len(list_rows) < floor * 0.9:
        warnings.append(
            f"{kind}: only {len(list_rows)} list rows, expected around {floor} "
            "- the feed looks truncated, so the counts below are incomplete"
        )
    return {
        rid: {"detail": detail, "list": lists.get(rid, {})}
        for rid, detail in by_id(details).items()
    }


def sev_links(mre_detail):
    """The SEV approvals an MRE rests on, from its published detail links."""
    found = {}
    for link in mre_detail.get("_links") or []:
        href = link.get("href") or ""
        if "SEVDetails" not in href:
            continue
        ids = parse_qs(urlparse(href).query).get("id")
        if ids:
            found[ids[0].lower()] = link.get("text") or ""
    return found


def scope_versions(mre_detail):
    return [
        link.get("href")
        for link in mre_detail.get("_links") or []
        if "DescriptorWorkInstruction" in (link.get("href") or "")
    ]


# ------------------------------------------------------------------ projection
def sev_view(rec):
    """The SEV side of a pair: what may be imported, and on what terms."""
    d, l = rec["detail"], rec["list"]
    start, end = nz.parse_bdr(d.get("SEVBDR"))
    expiry = nz.parse_any_date(
        l.get("rvr_approvalexpirydate__raw"),
        l.get("rvr_approvalexpirydate"),
        d.get("SEVExpiry"),
    )
    details_text = d.get("SEVVariantDetails")
    model_code = d.get("SEVModelCodeName") or l.get("rvr_modelcode") or None
    return {
        "approval": d.get("SEVApprovalNo"),
        "id": d.get("_id"),
        "url": d.get("_url"),
        "make": d.get("SEVMake"),
        "model": d.get("SEVModel"),
        "variant": d.get("SEVVariant"),
        "variant_details": details_text,
        # the free text often narrows eligibility below the structured range;
        # flagged and extracted for display only - nothing is computed from it
        "has_restriction_note": nz.has_restriction_hint(details_text),
        "restriction_dates_in_text": [
            nz.month_str(m) for m in nz.parse_prose_range(details_text)
        ] if nz.parse_prose_range(details_text)[0] else None,
        "model_code": model_code,
        "model_codes": nz.model_codes(model_code),
        "criterion": d.get("SEVCriterion"),
        "category": nz.category_code(d.get("SEVCategory")),
        "category_label": d.get("SEVCategory"),
        "build_range_text": d.get("SEVBDR"),
        "build_from": nz.month_str(start),
        "build_to": nz.month_str(end),
        "build_to_open_ended": start is not None and end is None,
        "expiry": expiry.isoformat() if expiry else None,
        "expiry_text": d.get("SEVExpiry") or l.get("rvr_approvalexpirydate"),
        "under_review": str(
            l.get("rvr_underreview__raw", l.get("rvr_underreview", ""))
        ).strip().lower() in ("true", "yes"),
        "state": l.get("statecode") or None,
    }


def mre_view(rec):
    """The MRE side: who can make it comply, for which build dates."""
    d, l = rec["detail"], rec["list"]
    build_text = d.get("BuildDate") or l.get("rvr_mrebuilddaterange")
    start, end = nz.parse_bdr(build_text)
    vin = d.get("rvr_identificationnumber")
    scopes = scope_versions(d)
    return {
        "approval": d.get("rvr_approvalnumber"),
        "id": d.get("_id"),
        "url": d.get("_url"),
        "make": d.get("rvr_manufacturercalc") or l.get("rvr_manufacturer"),
        "model": d.get("rvr_model"),
        "based_on": d.get("Based on"),
        "build_range_text": build_text,
        "build_from": nz.month_str(start),
        "build_to": nz.month_str(end),
        "build_to_open_ended": start is not None and end is None,
        "category": nz.category_code(d.get("rvr_categorycode")),
        "compliance_level": l.get("rvr_levelofcompliance"),
        # free text the department adds beside the grade, e.g. "Vehicle
        # Substantially Complies with ADR 79/04. Using Japanese standard JC08"
        "compliance_notes": d.get("rvr_compliancenotes"),
        "report_notes": d.get("rvr_additionalinformationpublishedmodelreport"),
        "body_shape": d.get("rvr_name"),
        "status": l.get("rvr_approvalstatus") or d.get("rvr_approvalstatus"),
        "report_type": d.get("rvr_approvalsubtypeid") or l.get("rvr_approvalsubtypeid"),
        "source_market": d.get("rvr_sourcemarketid"),
        "work_instruction_id": d.get("rvr_uniquedocumentidentifierworkinstructions"),
        "nsw_body_code": d.get("NSW body code"),
        "typical_vin": vin,
        "vin_patterns": nz.vin_patterns(vin),
        "scope_version_count": len(scopes),
        "scope_urls": scopes,
        "holder": d.get("rvr_publishedapprovalholder"),
        "contact": {
            "name": d.get("rvr_publishedcontact"),
            "phone": d.get("rvr_publishedphone"),
            "email": d.get("rvr_publishedemailaddress"),
            "website": d.get("rvr_publishedwebsite"),
        },
    }


def search_keys(sev, mre):
    """Everything an inspector might type: make, model, variant, model codes,
    the typical VIN, and both approval numbers. The page matches a typed
    chassis code as a substring of this, and a full VIN against vin_patterns."""
    parts = [
        sev["make"], sev["model"], sev["variant"], sev["model_code"],
        sev["approval"], mre["make"], mre["model"], mre["approval"],
        mre["typical_vin"], mre["work_instruction_id"], mre["holder"],
    ]
    return {
        "text": nz.norm_name(" ".join(p for p in parts if p)),
        "model_codes": sorted(set(sev["model_codes"])),
        "vin_patterns": mre["vin_patterns"],
    }


# ----------------------------------------------------------------- the pairing
def build(sev_recs, mre_recs):
    sev_views = {rid: sev_view(rec) for rid, rec in sev_recs.items()}
    pairs, unresolved, no_link, referenced = [], [], [], set()

    for rid, rec in sorted(
        mre_recs.items(),
        key=lambda kv: kv[1]["detail"].get("rvr_approvalnumber") or "",
    ):
        mre = mre_view(rec)
        links = sev_links(rec["detail"])
        # a report with no usable SEV link still has to be findable, so the
        # whole report is carried, not a summary of it
        if not links:
            no_link.append(
                {"mre": mre,
                 "note": "no SEV approval is linked on this report's detail page"}
            )
            continue
        for sev_id, text in links.items():
            sev = sev_views.get(sev_id)
            if sev is None:
                unresolved.append(
                    {"mre": mre, "sev_text": text, "sev_id": sev_id,
                     "note": "this report cites a SEV approval that is not in the "
                             "published SEVs Register (withdrawn or superseded)"}
                )
                continue
            referenced.add(sev_id)
            pairs.append({
                "sev": sev,
                "mre": mre,
                "search": search_keys(sev, mre),
            })

    pairs.sort(key=lambda p: (p["sev"]["approval"] or "", p["mre"]["approval"] or ""))
    return pairs, sev_views, referenced, unresolved, no_link


def coverage(pairs, sev_views, referenced, unresolved, no_link, counts, warnings):
    """What the paired dataset does and does not cover. Data completeness, not
    a judgement about any vehicle."""
    # the whole SEV view is kept, not a summary: a search for one of these
    # still has to show its criteria, variant details included
    unpaired = [
        dict(
            v,
            note="on the SEVs Register, but no Model Report cites it - nothing "
                 "to pair, so there is no workshop route to show",
        )
        for sid, v in sev_views.items()
        if sid not in referenced
    ]
    unpaired.sort(key=lambda r: r["approval"] or "")

    return {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": SOURCES,
            "row_counts": counts,
            "caveat": CAVEAT,
        },
        "summary": {
            "pairs": len(pairs),
            "sev_total": len(sev_views),
            "sev_paired": len(referenced),
            "sev_unpaired": len(unpaired),
            "mre_paired": len({p["mre"]["approval"] for p in pairs}),
            "mre_without_sev_link": len(no_link),
            "unresolved_sev_links": len(unresolved),
            "pairs_with_restriction_note": sum(
                1 for p in pairs if p["sev"]["has_restriction_note"]
            ),
            "criteria_seen": dict(
                collections.Counter(
                    p["sev"]["criterion"] or "(none)" for p in pairs
                ).most_common()
            ),
            "compliance_levels_seen": dict(
                collections.Counter(
                    p["mre"]["compliance_level"] or "(none)" for p in pairs
                ).most_common()
            ),
            "data_warnings": warnings,
        },
        "sev_without_model_report": unpaired,
        "unresolved_sev_links": unresolved,
        "mre_without_sev_link": no_link,
    }


def write(path, payload):
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def main(argv=None):
    global OUT

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT), help="directory to read and write")
    args = ap.parse_args(argv)
    OUT = pathlib.Path(args.out)

    warnings = []
    sev_list, mre_list = load("sev_list"), load("mre_list")
    sev_recs = merged(load("sev_details"), sev_list, "sev", warnings)
    mre_recs = merged(load("mre_details"), mre_list, "mre", warnings)
    counts = {
        "sev_list": len(sev_list), "sev_details": len(sev_recs),
        "mre_list": len(mre_list), "mre_details": len(mre_recs),
    }

    pairs, sev_views, referenced, unresolved, no_link = build(sev_recs, mre_recs)
    cover = coverage(pairs, sev_views, referenced, unresolved, no_link,
                     counts, warnings)

    write(OUT / "pairs.json", {"_meta": cover["_meta"], "pairs": pairs})
    write(OUT / "coverage.json", cover)

    s = cover["summary"]
    print(f"pairs              {s['pairs']}")
    print(f"SEV entries        {s['sev_total']}  "
          f"({s['sev_paired']} paired, {s['sev_unpaired']} with no Model Report)")
    print(f"MRE reports        {s['mre_paired']} paired, "
          f"{s['mre_without_sev_link']} with no SEV link, "
          f"{s['unresolved_sev_links']} citing a missing SEV")
    print(f"restriction notes  {s['pairs_with_restriction_note']} pairs carry "
          "SEV variant-details text that narrows eligibility - read it")
    for w in warnings:
        print(f"WARNING: {w}")
    print(f"wrote {OUT / 'pairs.json'} and {OUT / 'coverage.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
