"""Offline check of the parsing logic, using fixtures that mirror the real
markup and JSON shapes observed on rover.infrastructure.gov.au.
Run:  ./.venv/bin/python tests/test_offline.py
"""
import base64
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scrapy.http import HtmlResponse, Request, TextResponse
from rover.spiders.rover import RoverSpider
from rover.items import ApprovalItem, DetailItem

LIST_URL = "https://www.rover.infrastructure.gov.au/PublishedApprovals/MREApprovals/"

layouts = [{
    "Configuration": {"EntityName": "rvr_approval", "PrimaryKeyName": "rvr_approvalid"},
    "Base64SecureConfiguration": "U0lHTkVE",
    "SortExpression": "rvr_approvalnumber ASC",
    "Columns": [],
}]
list_html = (
    '<div class="entity-grid entitylist" '
    'data-get-url="/_services/entity-grid-data.json/c8825c88-ebd8-ee11-904d-000d3a7a0265" '
    'data-view-layouts="%s"></div>'
) % base64.b64encode(json.dumps(layouts).encode()).decode()

token_html = '<input name="__RequestVerificationToken" type="hidden" value="TOKEN123" />'

grid_json = {
    "MoreRecords": True,
    "ItemCount": 926,
    "NextPagePagingCookie": "COOKIE1",
    "Records": [{
        "Id": "2cb61393-ce5b-ec11-a305-0050569e60b7",
        "EntityName": "rvr_approval",
        "Attributes": [
            {"Name": "rvr_approvalnumber", "Value": "MRE-000001",
             "DisplayValue": "MRE-000001", "AttributeMetadata": {"huge": "x" * 1000}},
            {"Name": "a_cb372b792682ec118d2100224815106d.rvr_manufacturer",
             "Value": "Toyota", "DisplayValue": "Toyota", "AttributeMetadata": {}},
            {"Name": "statecode", "Value": {"Value": 0}, "DisplayValue": "Active",
             "AttributeMetadata": {}},
            {"Name": "rvr_approvalexpirydate", "Value": "2026-10-17T00:00:00Z",
             "DisplayValue": "17/10/2026", "AttributeMetadata": {}},
        ],
    }],
}

# Not every value sits in a table row: some live in section blocks with an
# <h3 class="lsh"> heading, which is where "Compliance level notes" is.
detail_sections = """
<div class="ls "><h3 class="lsh">Compliance level notes</h3>
  <div class="question-body">
    <div id="rvr_compliancenotes" class="question-label">Vehicle Substantially Complies with ADR 79/04. Using Japanese standard JC08 for compliance.</div>
  </div>
</div>
<div class="ls "><h3 class="lsh">Model Report notes</h3>
  <div class="question-body">
    <div id="rvr_additionalinformationpublishedmodelreport" class="question-label">HONDA FREED WELFARE GB5/GB6 SERIES WAGON - L15B 1.5LT PETROL</div>
  </div>
</div>
"""

detail_html = """
<div class="crmEntityFormView"><table><tbody>
<tr><td class="question-text-inline"><div class="qtdiv">Approval Number</div></td>
    <td><div class="question-body"><div id="rvr_approvalnumber" class="question-label">MRE-000001</div></div></td></tr>
<tr><td class="question-text-inline"><div class="qtdiv">Make</div></td>
    <td><div class="question-body"><div id="rvr_manufacturercalc" class="question-label">Toyota</div></div></td></tr>
<tr><td class="question-text-inline"><div class="qtdiv">Typical VIN</div></td>
    <td><div class="question-body"><div id="rvr_identificationnumber" class="question-label">6XXXZWE211XXXXXXX</div></div></td></tr>
<tr><td class="question-text-inline"><div class="qtdiv">NSW body code</div></td>
    <td><div class="question-body"></div></td></tr>
</tbody></table>
<a href="/PublishedApprovals/SEVDetails/?id=deb1aa5a-a56d-ef11-a670-000d3ad0c85d">SEV-000643</a>
<a href="MREDescriptorWorkInstruction?id=2cb61393&amp;apprversionid=070a757b">View current Model Report Scope</a>
<a href="/PublishedApprovals/MREApprovals">Return to list</a>
</div>
"""


def resp(url, body, cls=HtmlResponse, headers=None):
    return cls(url=url, body=body.encode(), encoding="utf-8",
               request=Request(url), headers=headers or {})


def main():
    failures = []

    def check(name, cond, extra=""):
        print(("  PASS  " if cond else "  FAIL  ") + name + ("  " + extra if extra else ""))
        if not cond:
            failures.append(name)

    spider = RoverSpider(list="mre", details=1, page_size=50)

    # --- step 1: grid config extraction -------------------------------------
    out = list(spider.parse_list_page(resp(LIST_URL, list_html)))
    token_req = out[0]
    cfg = token_req.cb_kwargs["grid_cfg"]
    print("grid config")
    check("endpoint url", cfg["get_url"].endswith(
        "/_services/entity-grid-data.json/c8825c88-ebd8-ee11-904d-000d3a7a0265"), cfg["get_url"])
    check("signed config decoded", cfg["config"] == "U0lHTkVE")
    check("sort expression", cfg["sort"] == "rvr_approvalnumber ASC")
    check("token endpoint", "/_layout/tokenhtml" in token_req.url)

    # --- step 2: token ------------------------------------------------------
    print("antiforgery token")
    grid_req = list(spider.parse_token(
        resp(f"{spider.__class__.__module__ and 'https://www.rover.infrastructure.gov.au'}/_layout/tokenhtml", token_html),
        cfg, 1, ""))[0]
    body = json.loads(grid_req.body)
    check("method is POST", grid_req.method == "POST")
    check("X-Requested-With header",
          grid_req.headers.get("X-Requested-With") == b"XMLHttpRequest")
    check("token header", grid_req.headers.get("__RequestVerificationToken") == b"TOKEN123")
    check("body carries signed config", body["base64SecureConfiguration"] == "U0lHTkVE")
    check("page/pageSize", body["page"] == 1 and body["pageSize"] == 50)
    check("pagingCookie empty on page 1", body["pagingCookie"] == "")

    # --- step 3: grid JSON --------------------------------------------------
    print("grid response")
    results = list(spider.parse_grid(
        resp(cfg["get_url"], json.dumps(grid_json), TextResponse,
             {"Content-Type": "application/json; charset=utf-8"}),
        cfg, "TOKEN123", 1))
    items = [r for r in results if isinstance(r, ApprovalItem)]
    reqs = [r for r in results if isinstance(r, Request)]
    row = items[0]
    check("one row flattened", len(items) == 1)
    check("link-entity prefix stripped", "rvr_manufacturer" in row, str(sorted(row)[:4]))
    check("display value kept", row["rvr_approvalexpirydate"] == "17/10/2026")
    check("raw value kept alongside",
          row["rvr_approvalexpirydate__raw"] == "2026-10-17T00:00:00Z")
    check("metadata discarded", not any("AttributeMetadata" in k for k in row))
    check("optionset uses display value", row["statecode"] == "Active")
    detail_reqs = [r for r in reqs if "ModelReportDetails" in r.url]
    next_pages = [r for r in reqs if r.method == "POST"]
    check("detail request queued", len(detail_reqs) == 1,
          detail_reqs[0].url if detail_reqs else "")
    check("next page uses pagingCookie",
          bool(next_pages) and json.loads(next_pages[0].body)["pagingCookie"] == "COOKIE1")
    check("next page number", bool(next_pages) and json.loads(next_pages[0].body)["page"] == 2)

    # HTML instead of JSON must re-arm the token, not crash
    rearm = list(spider.parse_grid(resp(cfg["get_url"], "<html></html>"), cfg, "T", 3))
    check("stale token re-arms", len(rearm) == 1 and "/_layout/tokenhtml" in rearm[0].url)

    # --- step 4: detail page ------------------------------------------------
    print("detail page")
    d = list(spider.parse_detail(
        resp("https://www.rover.infrastructure.gov.au/PublishedApprovals/ModelReportDetails/?id=2cb61393-ce5b-ec11-a305-0050569e60b7",
             detail_html + detail_sections),
        "2cb61393-ce5b-ec11-a305-0050569e60b7"))[0]
    check("is a DetailItem", isinstance(d, DetailItem))
    check("keyed by logical name", d["rvr_approvalnumber"] == "MRE-000001")
    check("vin parsed", d["rvr_identificationnumber"] == "6XXXZWE211XXXXXXX")
    check("empty value is None", d["NSW body code"] is None)
    check("human labels kept", d["_labels"]["rvr_manufacturercalc"] == "Make")
    hrefs = [l["href"] for l in d["_links"]]
    check("linked SEV captured", any("SEVDetails" in h for h in hrefs))
    check("scope link captured", any("DescriptorWorkInstruction" in h for h in hrefs))
    check("nav link ignored", not any(h.endswith("/MREApprovals") for h in hrefs))
    check("compliance level notes captured from a section block",
          d["rvr_compliancenotes"].startswith("Vehicle Substantially Complies with ADR 79/04"))
    check("section heading used as the label",
          d["_labels"]["rvr_compliancenotes"] == "Compliance level notes")
    check("model report notes captured too",
          d["rvr_additionalinformationpublishedmodelreport"].startswith("HONDA FREED WELFARE")
          and d["_labels"]["rvr_additionalinformationpublishedmodelreport"]
              == "Model Report notes")
    check("row-based fields still win over the section sweep",
          d["rvr_approvalnumber"] == "MRE-000001")

    print()
    if failures:
        print(f"{len(failures)} FAILED: {failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
