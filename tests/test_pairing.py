"""Offline check of the normalisation and SEV<->MRE pairing logic, using
fixtures that mirror the real field names and value formats observed on
rover.infrastructure.gov.au.

Run:  ./.venv/bin/python tests/test_pairing.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from rover import normalize as nz
from rover import pair

BASE = "https://www.rover.infrastructure.gov.au"
SEV_URL = BASE + "/PublishedApprovals/SEVDetails/?id="
MRE_URL = BASE + "/PublishedApprovals/ModelReportDetails/?id="

# GUIDs stand in for the real record ids; only identity matters.
A, B, C, D, E, F, G, H, I = (
    f"{c * 8}-0000-0000-0000-000000000000" for c in "abcdefghi")
GHOST = "99999999-0000-0000-0000-000000000000"   # cited by an MRE, not in the register


def sev_detail(rid, no, make, model, bdr, criterion="Rarity Criterion",
               category="MA - Passenger Vehicle", variant="Base", expiry="01/01/2099",
               variant_details=None):
    return {
        "_id": rid, "_url": SEV_URL + rid,
        "SEVApprovalNo": no, "SEVMake": make, "SEVModel": model,
        "SEVCategory": category, "SEVBDR": bdr, "SEVVariant": variant,
        "SEVVariantDetails": variant_details, "SEVCriterion": criterion,
        "SEVExpiry": expiry, "SEVModelCodeName": "ZZE123", "_links": [],
    }


def sev_row(rid, expiry_raw="/Date(1945871180000)/", expiry="30/08/2031",
            under_review=False, state="Active"):
    return {
        "_id": rid, "statecode": state, "rvr_modelcode": "ZZE123",
        "rvr_underreview": "Yes" if under_review else "No",
        "rvr_underreview__raw": under_review,
        "rvr_approvalexpirydate": expiry,
        "rvr_approvalexpirydate__raw": expiry_raw,
    }


def mre_detail(rid, no, make, model, build, holder, sevs, category="MA", scopes=1):
    links = [{"text": t, "href": SEV_URL + sid} for sid, t in sevs]
    links += [
        {"text": "View current Model Report Scope",
         "href": BASE + "/PublishedApprovals/ModelReportDetails/"
                        f"MREDescriptorWorkInstruction?id={rid}&apprversionid={n}"}
        for n in range(scopes)
    ]
    return {
        "_id": rid, "_url": MRE_URL + rid,
        "rvr_approvalnumber": no, "rvr_manufacturercalc": make, "rvr_model": model,
        "BuildDate": build, "rvr_categorycode": category,
        "rvr_publishedapprovalholder": holder,
        "rvr_identificationnumber": "6XXXXAHR20XXXXXXX",
        "rvr_sourcemarketid": "Japan",
        "rvr_uniquedocumentidentifierworkinstructions": "WIZRR701I",
        "Based on": None, "NSW body code": None, "_links": links,
    }


def mre_row(rid, status="In Force", compliance="Complies"):
    return {
        "_id": rid, "rvr_approvalstatus": status,
        "rvr_levelofcompliance": compliance,
        "rvr_approvalsubtypeid": "Specialist and Enthusiast Vehicles",
    }


def raw_row(no, holder, expiry_raw="/Date(1877500000000)/", status="In Force"):
    return {
        "_id": no, "rvr_approvalnumber": no, "rvr_holderofapprovalid": holder,
        "rvr_approvalstatus": status,
        "rvr_approvalexpirydate_": None,
        "rvr_approvalexpirydate": "30/06/2029",
        "rvr_approvalexpirydate__raw": expiry_raw,
        "rvr_publishedcontact": "MAHESH (MIKE) GODAVITARANE",
        "rvr_publishedphone": "0421681826",
        "rvr_publishedemailaddress": "sales@example.com.au",
        "rvr_publishedwebsite": "https://example.com.au",
    }


# ------------------------------------------------------------------- fixtures
# A: the good SEV, hand-verified shape (Toyota 70 Series Welcab)
# B: open-ended build range ("No end date")
# C: expired    D: orphan (nothing cites it)    E: under review    F: disjoint build
sev_details = [
    sev_detail(A, "SEV-000675", "Toyota", "70 Series Welcab", "06/2007 - 12/2013",
               criterion="Mobility Criterion", variant="Welcab"),
    sev_detail(B, "SEV-000667", "Honda", "Fit Hybrid", "01/2023 - No end date"),
    sev_detail(C, "SEV-000003", "Nissan", "Skyline", "01/1999 - 12/2002"),
    sev_detail(D, "SEV-000004", "Mazda", "Eunos Cosmo", "01/1990 - 12/1995"),
    sev_detail(E, "SEV-000005", "Subaru", "Impreza", "01/2001 - 12/2007"),
    sev_detail(F, "SEV-000006", "Lexus", "LFA", "12/2010 - 03/2011"),
    # a second variant of the same vehicle as A: the usual reason one Model
    # Report cites more than one SEV
    sev_detail(G, "SEV-000676", "Toyota", "70 Series Welcab", "06/2007 - 12/2013",
               criterion="Mobility Criterion", variant="Welcab high-roof"),
    # verbatim wording seen on SEV-000557: the prose is narrower than SEVBDR
    sev_detail(H, "SEV-000557", "Toyota", "Vellfire", "01/2010 - 12/2014",
               variant_details="Eligible build date range limited to "
                               "1/03/2010 to 20/07/2010 ONLY"),
    # verbatim wording seen on SEV-000554: a restriction no parser can apply
    sev_detail(I, "SEV-000554", "Honda", "Integra", "01/2001 - 12/2006",
               variant_details="2 door, K20A series motor, ONLY."),
]
sev_lists = [
    sev_row(A), sev_row(B, expiry_raw=None, expiry="01/01/2099"),
    sev_row(C, expiry_raw="/Date(1577836800000)/", expiry="01/01/2020"),
    sev_row(D), sev_row(E, under_review=True), sev_row(F), sev_row(G),
    sev_row(H), sev_row(I),
]

GLAM = "GLAM GROUPS PTY. LTD."
mre_details = [
    # one report citing two SEVs, and the only fully clean route
    mre_detail("m02", "MRE-000002", "Toyota", "70 Series Welcab", "6/2007 - 12/2013",
               GLAM, [(A, "SEV-000675"), (G, "SEV-000676")], scopes=3),
    # a second workshop citing the same SEV -> many-to-many on both sides
    mre_detail("m03", "MRE-000003", "Toyota", "70 Series Welcab", "6/2007 - 12/2013",
               "Unregistered Motors Pty Ltd", [(A, "SEV-000675")]),
    mre_detail("m04", "MRE-000004", "Nissan", "Skyline", "1/1999 - 12/2002",
               GLAM, [(C, "SEV-000003")]),
    mre_detail("m05", "MRE-000005", "Subaru", "Impreza", "1/2001 - 12/2007",
               GLAM, [(E, "SEV-000005")]),
    mre_detail("m06", "MRE-000006", "Lexus", "LFA", "1/2015 - 12/2018",
               GLAM, [(F, "SEV-000006")]),
    mre_detail("m07", "MRE-000007", "Toyota", "Estima", "1/2006 - 10/2019",
               GLAM, [(GHOST, "SEV-000999")]),
    mre_detail("m08", "MRE-000008", "Toyota", "Crown", "2/2008 - 7/2013", GLAM, []),
    mre_detail("m09", "MRE-000009", "Honda", "Fit Hybrid", "7/2023 - No end date",
               "Lapsed Workshops Pty Ltd", [(B, "SEV-000667")]),
    mre_detail("m10", "MRE-000010", "Honda", "Fit Hybrid", "7/2023 - No end date",
               GLAM, [(B, "SEV-000667")]),
    # linked pair whose make/model wording and category both disagree
    mre_detail("m11", "MRE-000011", "Nissan", "Patrol", "6/2007 - 12/2013",
               GLAM, [(A, "SEV-000675")], category="NB"),
    # report covering the whole structured SEV range, which the prose narrows
    mre_detail("m12", "MRE-000012", "Toyota", "Vellfire", "1/2010 - 12/2014",
               GLAM, [(H, "SEV-000557")]),
    mre_detail("m13", "MRE-000013", "Honda", "Integra", "1/2001 - 12/2006",
               GLAM, [(I, "SEV-000554")]),
]
mre_lists = [
    mre_row("m02"), mre_row("m03"), mre_row("m04"), mre_row("m05"), mre_row("m06"),
    mre_row("m07"), mre_row("m08"), mre_row("m09"),
    mre_row("m10", status="Withdrawn"), mre_row("m11"), mre_row("m12"),
    mre_row("m13"),
]
raw_rows = [
    # punctuation deliberately differs from the MRE spelling of the same company
    raw_row("RAW-000001", "Glam Groups Pty Ltd"),
    raw_row("RAW-000009", "Lapsed Workshops Pty Ltd",
            expiry_raw="/Date(1577836800000)/"),
]


def main():
    failures = []

    def check(name, cond, extra=""):
        print(("  PASS  " if cond else "  FAIL  ") + name + ("  " + extra if extra else ""))
        if not cond:
            failures.append(name)

    # --- normalisation ------------------------------------------------------
    print("date and name normalisation")
    check("month, unpadded (MRE style)", nz.parse_month("7/2017") == (2017, 7))
    check("month, padded (SEV style)", nz.parse_month("05/2011") == (2011, 5))
    check("month rejects junk", nz.parse_month("n/a") is None)
    check("closed build range", nz.parse_bdr("05/2011 - 09/2020") == ((2011, 5), (2020, 9)))
    check("open-ended range keeps start",
          nz.parse_bdr("01/2023 - No end date") == ((2023, 1), None))
    check("unparsed range is not open-ended", nz.parse_bdr("") == (None, None))
    check("d/m/Y expiry", nz.parse_dmy("29/11/2026").isoformat() == "2026-11-29")
    check("d/m/Y single-digit day", nz.parse_dmy("1/01/2017").isoformat() == "2017-01-01")
    check("dataverse epoch date",
          nz.parse_dataverse_date("/Date(1483228800000)/").isoformat() == "2017-01-01")
    check("raw epoch preferred over display",
          nz.parse_any_date("/Date(1483228800000)/", "29/11/2026").isoformat()
          == "2017-01-01")
    check("company name normalised",
          nz.norm_name("GLAM GROUPS PTY. LTD.") == nz.norm_name("Glam Groups Pty Ltd"))
    check("category code extracted", nz.category_code("MA - Passenger Vehicle") == "MA")
    check("category code idempotent", nz.category_code("MA") == "MA")
    check("vin wildcards expanded",
          nz.vin_patterns("6XXXXAHR20XXXXXXX") == ["^6....AHR20.......$"])
    check("model codes split", nz.model_codes("ZVW40/ZVW41") == ["ZVW40", "ZVW41"])
    check("model code hyphen kept", nz.model_codes("B-G") == ["B-G"])

    # --- pairing ------------------------------------------------------------
    print("pairing")
    warnings = []
    sev_recs = pair.merged(sev_details, sev_lists, "sev", warnings)
    mre_recs = pair.merged(mre_details, mre_lists, "mre", warnings)
    pairs, sev_views, referenced, unresolved, no_link = pair.build(
        sev_recs, mre_recs
    )
    counts = {"sev_details": len(sev_recs), "mre_details": len(mre_recs)}
    cover = pair.coverage(pairs, sev_views, referenced, unresolved, no_link,
                          counts, warnings)
    index = {(p["sev"]["approval"], p["mre"]["approval"]): p for p in pairs}

    check("one report citing two SEVs makes two pairs",
          len([p for p in pairs if p["mre"]["approval"] == "MRE-000002"]) == 2)
    check("two reports citing one SEV both pair",
          len([p for p in pairs if p["sev"]["approval"] == "SEV-000675"]) == 3,
          str(sorted(p["mre"]["approval"] for p in pairs
                     if p["sev"]["approval"] == "SEV-000675")))
    check("pair count", len(pairs) == 11, str(len(pairs)))
    check("no eligibility verdict is emitted",
          not any(k in pairs[0] for k in ("status", "blockers", "blocked_by",
                                          "envelope", "warnings")),
          str(sorted(pairs[0])))

    good = index[("SEV-000675", "MRE-000002")]
    check("both build ranges kept side by side, verbatim",
          good["sev"]["build_range_text"] == "06/2007 - 12/2013"
          and good["mre"]["build_range_text"] == "6/2007 - 12/2013")
    check("build months parsed for display",
          good["sev"]["build_from"] == "06/2007"
          and good["mre"]["build_from"] == "06/2007")
    check("criterion carried", good["sev"]["criterion"] == "Mobility Criterion")
    check("sev expiry parsed and kept as text",
          good["sev"]["expiry"] == "2031-08-30"
          and good["sev"]["expiry_text"] is not None)
    check("approval holder carried from the report",
          good["mre"]["holder"] == GLAM)
    check("no workshop register is joined",
          "raw" not in pairs[0])
    check("compliance level carried from the list row",
          good["mre"]["compliance_level"] == "Complies")
    check("scope versions counted", good["mre"]["scope_version_count"] == 3)
    open_ended = index[("SEV-000667", "MRE-000009")]
    check("open-ended build range flagged, not invented",
          open_ended["sev"]["build_to"] is None
          and open_ended["sev"]["build_to_open_ended"] is True
          and open_ended["sev"]["build_range_text"] == "01/2023 - No end date")

    # --- what an inspector types -------------------------------------------
    print("search keys")
    check("model codes exposed for chassis search",
          "ZZE123" in good["search"]["model_codes"])
    check("vin pattern exposed for full-VIN search",
          good["search"]["vin_patterns"] == ["^6....AHR20.......$"])
    check("haystack covers make, model and approvals",
          all(t in good["search"]["text"] for t in
              ("TOYOTA", "70 SERIES WELCAB", "SEV-000675", "MRE-000002")),
          good["search"]["text"][:90])
    check("haystack covers the typical VIN and workshop",
          "6XXXXAHR20XXXXXXX" in good["search"]["text"]
          and "GLAM GROUPS PTY LTD" in good["search"]["text"])

    # --- variant details: surfaced for the inspector, never applied --------
    print("variant details restrictions")
    check("prose range parsed from real wording",
          nz.parse_prose_range("Eligible build date range limited to "
                               "1/03/2010 to 20/07/2010 ONLY") == ((2010, 3), (2010, 7)))
    check("prose range parsed with 'range of' wording",
          nz.parse_prose_range("SEVS eligibility restricted to USF 40 and USF 41 "
                               "(2WD) with build date range of 1/09/2006 to 30/04/2007")
          == ((2006, 9), (2007, 4)))
    check("trim-only restriction yields no dates",
          nz.parse_prose_range("2 door, K20A series motor, ONLY.") == (None, None))
    check("trim-only restriction still flagged",
          nz.has_restriction_hint("2 door, K20A series motor, ONLY."))
    check("plain variant text is not a restriction",
          not nz.has_restriction_hint("Welcab variants"))

    restricted = index[("SEV-000557", "MRE-000012")]
    check("restriction text kept verbatim",
          restricted["sev"]["variant_details"]
          == "Eligible build date range limited to 1/03/2010 to 20/07/2010 ONLY")
    check("restriction flagged for attention",
          restricted["sev"]["has_restriction_note"] is True)
    check("dates in the text extracted for display",
          restricted["sev"]["restriction_dates_in_text"] == ["03/2010", "07/2010"])
    check("structured range left untouched by the text",
          restricted["sev"]["build_from"] == "01/2010"
          and restricted["sev"]["build_to"] == "12/2014",
          "the narrowing is shown, not applied - the inspector decides")

    unreadable = index[("SEV-000554", "MRE-000013")]
    check("trim-only restriction flagged with no dates",
          unreadable["sev"]["has_restriction_note"] is True
          and unreadable["sev"]["restriction_dates_in_text"] is None)
    check("plain pair carries no restriction note",
          good["sev"]["has_restriction_note"] is False)

    # --- coverage, not judgement -------------------------------------------
    print("coverage report")
    unpaired = [o["approval"] for o in cover["sev_without_model_report"]]
    check("SEV with no Model Report listed", unpaired == ["SEV-000004"], str(unpaired))
    check("unpaired entry keeps its whole criteria set, not a summary",
          all(k in cover["sev_without_model_report"][0] for k in
              ("variant_details", "criterion", "build_range_text", "expiry_text",
               "model_codes")))
    check("and explained as a data gap, not a refusal",
          "nothing to pair" in cover["sev_without_model_report"][0]["note"])
    check("unresolved SEV link captured",
          [u["mre"]["approval"] for u in cover["unresolved_sev_links"]] == ["MRE-000007"])
    check("report citing nothing is kept, not dropped",
          [n["mre"]["approval"] for n in cover["mre_without_sev_link"]] == ["MRE-000008"])
    check("an unpaired report keeps its whole detail, so it stays searchable",
          all(k in cover["unresolved_sev_links"][0]["mre"] for k in
              ("build_range_text", "compliance_level", "typical_vin", "holder", "url"))
          )

    s_ = cover["summary"]
    check("summary counts the join",
          s_["pairs"] == len(pairs) and s_["sev_total"] == 9
          and s_["sev_paired"] == 8 and s_["sev_unpaired"] == 1)
    check("summary counts restriction notes",
          s_["pairs_with_restriction_note"] == 2,
          str(s_["pairs_with_restriction_note"]))
    check("criteria and compliance levels tallied",
          s_["criteria_seen"].get("Mobility Criterion") == 4
          and sum(s_["criteria_seen"].values()) == len(pairs)
          and "Complies" in s_["compliance_levels_seen"])
    check("truncated feed warned",
          any("looks truncated" in w for w in s_["data_warnings"]),
          str(s_["data_warnings"]))
    check("caveat says no verdict is computed",
          "not a decision" in cover["_meta"]["caveat"]
          and cover["_meta"]["sources"]["sev"].endswith("/SEVApprovals/"))

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
