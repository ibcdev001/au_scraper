"""
ROVER published-approvals spider.

rover.infrastructure.gov.au is a Microsoft Power Pages (Dataverse) portal.
There is no documented public API, but the list grids are backed by an
internal JSON endpoint:

    POST /_services/entity-grid-data.json/<entity-list-id>

Three things are required or the server silently returns the HTML page
instead of JSON:
  * header  X-Requested-With: XMLHttpRequest
  * header  __RequestVerificationToken  (fetched from /_layout/tokenhtml)
  * body    base64SecureConfiguration   (a signed view config scraped out of
            the list page's data-view-layouts attribute)

Paging past the first page needs `pagingCookie`, echoed from the previous
response's NextPagePagingCookie.

Detail pages are server-rendered HTML, so no browser automation is needed.
Each value <div> carries its Dataverse logical name as the element id, which
makes the parse stable rather than position-dependent.

Run:
    scrapy crawl rover -a list=mre
    scrapy crawl rover -a list=mre -a details=1
    scrapy crawl rover -a list=sev -a max_pages=1     # smoke test
"""

import base64
import json
import time
from urllib.parse import urljoin

import scrapy

from rover.items import ApprovalItem, DetailItem

BASE = "https://www.rover.infrastructure.gov.au"

LISTS = {
    "sev": "/PublishedApprovals/SEVApprovals/",
    "mre": "/PublishedApprovals/MREApprovals/",
    "vta": "/PublishedApprovals/VTAApprovals/",
    "avv": "/PublishedApprovals/AVVApprovals/",
    "cta": "/PublishedApprovals/CTAApprovals/",
    "raw": "/PublishedApprovals/RAWApprovals/",
    "tf": "/PublishedApprovals/TFApprovals/",
}

DETAIL_PAGES = {
    "mre": "/PublishedApprovals/ModelReportDetails/",
    "sev": "/PublishedApprovals/SEVDetails/",
}


class RoverSpider(scrapy.Spider):
    name = "rover"
    allowed_domains = ["rover.infrastructure.gov.au"]

    custom_settings = {
        "FEEDS": {
            "output/%(list_key)s_list.json": {
                "format": "json",
                "encoding": "utf-8",
                "indent": 2,
                "overwrite": True,
                "item_classes": ["rover.items.ApprovalItem"],
            },
            "output/%(list_key)s_details.json": {
                "format": "json",
                "encoding": "utf-8",
                "indent": 2,
                "overwrite": True,
                "item_classes": ["rover.items.DetailItem"],
                "store_empty": False,
            },
        }
    }

    def __init__(self, list="mre", details=0, page_size=50, max_pages=0, *a, **kw):
        super().__init__(*a, **kw)
        self.list_key = str(list).lower()
        if self.list_key not in LISTS:
            raise ValueError(f"list must be one of {sorted(LISTS)}")
        self.want_details = str(details) not in ("0", "", "false", "False")
        self.page_size = int(page_size)
        self.max_pages = int(max_pages)
        self.seen = 0
        self.total = None

    # ---------------------------------------------------------------- step 1
    def start_requests(self):
        yield scrapy.Request(
            urljoin(BASE, LISTS[self.list_key]),
            callback=self.parse_list_page,
            dont_filter=True,
        )

    async def start(self):
        """Scrapy >= 2.13 entry point; start_requests() is kept for older ones."""
        for request in self.start_requests():
            yield request

    def parse_list_page(self, response):
        """Lift the endpoint URL and the signed view config off the grid div."""
        grid = response.css("[data-view-layouts]")
        if not grid:
            raise scrapy.exceptions.CloseSpider(
                f"no entity grid on {response.url} - the page layout may have changed"
            )

        layouts = json.loads(base64.b64decode(grid.attrib["data-view-layouts"]))
        layout = layouts[0]
        grid_cfg = {
            "get_url": response.urljoin(grid.attrib["data-get-url"]),
            "config": layout["Base64SecureConfiguration"],
            "sort": layout.get("SortExpression") or "",
            "entity": layout["Configuration"]["EntityName"],
            "referer": response.url,
        }
        self.logger.info(
            "grid: entity=%s endpoint=%s", grid_cfg["entity"], grid_cfg["get_url"]
        )
        yield self.token_request(grid_cfg, page=1, paging_cookie="")

    # ---------------------------------------------------------------- step 2
    def token_request(self, grid_cfg, page, paging_cookie):
        """Power Pages hands out a fresh antiforgery token from this endpoint."""
        return scrapy.Request(
            f"{BASE}/_layout/tokenhtml?_={int(time.time() * 1000)}",
            callback=self.parse_token,
            cb_kwargs={"grid_cfg": grid_cfg, "page": page, "paging_cookie": paging_cookie},
            dont_filter=True,
        )

    def parse_token(self, response, grid_cfg, page, paging_cookie):
        token = response.css('input[name="__RequestVerificationToken"]::attr(value)').get()
        if not token:
            raise scrapy.exceptions.CloseSpider("could not read __RequestVerificationToken")
        yield self.grid_request(grid_cfg, token, page, paging_cookie)

    # ---------------------------------------------------------------- step 3
    def grid_request(self, grid_cfg, token, page, paging_cookie):
        body = {
            "base64SecureConfiguration": grid_cfg["config"],
            "sortExpression": grid_cfg["sort"],
            "search": None,
            "page": page,
            "pageSize": self.page_size,
            "pagingCookie": paging_cookie,
            "filter": None,
            "metaFilter": None,
            "nlSearchFilter": "",
            "timezoneOffset": -600,      # AEST; only affects how dates are rendered
            "customParameters": [],
        }
        return scrapy.Request(
            grid_cfg["get_url"],
            method="POST",
            body=json.dumps(body),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",   # omit this and you get HTML
                "__RequestVerificationToken": token,
                "Referer": grid_cfg["referer"],
            },
            callback=self.parse_grid,
            cb_kwargs={"grid_cfg": grid_cfg, "token": token, "page": page},
            dont_filter=True,
        )

    def parse_grid(self, response, grid_cfg, token, page):
        ctype = response.headers.get("Content-Type", b"").decode("latin-1")
        if "json" not in ctype:
            # Token went stale and the portal served the page instead. Re-arm.
            self.logger.warning("page %s came back as HTML; refreshing token", page)
            yield self.token_request(grid_cfg, page, "")
            return

        data = json.loads(response.text)
        self.total = data.get("ItemCount", self.total)

        for record in data["Records"]:
            self.seen += 1
            item = self.flatten(record)
            yield item
            if self.want_details and self.list_key in DETAIL_PAGES:
                detail_url = f"{urljoin(BASE, DETAIL_PAGES[self.list_key])}?id={item['_id']}"
                yield scrapy.Request(
                    detail_url,
                    callback=self.parse_detail,
                    cb_kwargs={"record_id": item["_id"]},
                    priority=-10,          # finish the list before chasing details
                )

        self.logger.info("[%s] page %s -> %s/%s rows", self.list_key, page, self.seen, self.total)

        if data.get("MoreRecords") and not (self.max_pages and page >= self.max_pages):
            yield self.grid_request(
                grid_cfg, token, page + 1, data.get("NextPagePagingCookie") or ""
            )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def flatten(record):
        """Record -> flat dict, discarding the AttributeMetadata blob."""
        item = ApprovalItem(_id=record["Id"], _entity=record["EntityName"])
        for attr in record["Attributes"]:
            # strip the a_<hash>. prefix that link-entity columns carry
            key = attr["Name"].split(".")[-1]
            item[key] = attr.get("DisplayValue")
            raw = attr.get("Value")
            if isinstance(raw, (str, int, float)) and raw != attr.get("DisplayValue"):
                item[key + "__raw"] = raw
        return item

    def parse_detail(self, response, record_id):
        """Detail pages are server-rendered; value div ids are logical names."""
        item = DetailItem(_id=record_id, _url=response.url)
        labels = {}

        for row in response.css("tr"):
            label = row.css(".qtdiv::text").get()
            if not label or not label.strip():
                continue
            label = label.strip()
            value_el = row.css(".question-label")
            key = (value_el.attrib.get("id") if value_el else None) or label
            value = " ".join(value_el.css("::text").getall()).strip() if value_el else None
            item[key] = value or None
            labels[key] = label

        # Some values sit in section blocks (<div class="ls"><h3 class="lsh">)
        # instead of table rows - "Compliance level notes" and "Model Report
        # notes" among them - so sweep up every id'd value the row pass missed.
        for el in response.css(".question-label[id]"):
            key = el.attrib["id"]
            value = " ".join(el.css("::text").getall()).strip()
            if not value or item.get(key):
                continue
            item[key] = value
            heading = el.xpath(
                "ancestor::div[contains(concat(' ', normalize-space(@class), ' '),"
                " ' ls ')][1]/h3[contains(concat(' ', normalize-space(@class), ' '),"
                " ' lsh ')]/text()"
            ).get()
            labels[key] = (heading or key).strip()

        item["_labels"] = labels
        item["_links"] = [
            {
                "text": " ".join(a.css("::text").getall()).strip(),
                "href": response.urljoin(a.attrib["href"]),
            }
            for a in response.css("a[href]")
            if "Details" in a.attrib["href"] or "DescriptorWorkInstruction" in a.attrib["href"]
        ]
        yield item
