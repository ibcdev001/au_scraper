# Au_Scraper — ROVER published approvals

Scrapy crawler for the Australian Department of Infrastructure's ROVER register
(`rover.infrastructure.gov.au`): the SEVs Register, approved Model Reports, and
the other published-approvals lists.

## Why it works the way it does

ROVER has **no documented public API**. It's a Microsoft Power Pages (Dataverse)
portal, and its list grids are fed by an internal JSON endpoint:

```
POST /_services/entity-grid-data.json/c8825c88-ebd8-ee11-904d-000d3a7a0265
```

Both SEV and MRE use the *same* endpoint id — which view you get is decided by a
signed `base64SecureConfiguration` blob that the spider scrapes off the list
page's `data-view-layouts` attribute. Three things are required or the server
quietly returns the HTML page instead of JSON:

| requirement | where it comes from |
|---|---|
| `X-Requested-With: XMLHttpRequest` header | hardcoded |
| `__RequestVerificationToken` header | `GET /_layout/tokenhtml` |
| `base64SecureConfiguration` in the body | the list page's grid div |

Paging past page 1 needs `pagingCookie`, echoed from the previous response's
`NextPagePagingCookie`.

Detail pages are **server-rendered HTML**, so no Playwright or browser
automation is needed anywhere. Each value `<div>` carries its Dataverse logical
name as the element id (`rvr_approvalnumber`, `rvr_identificationnumber`, …),
so the parse is keyed on those rather than on column position.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

## Run

```bash
# smoke test first — one page, ~50 rows
./.venv/bin/scrapy crawl rover -a list=mre -a max_pages=1

# full list
./.venv/bin/scrapy crawl rover -a list=mre
./.venv/bin/scrapy crawl rover -a list=sev

# list + every detail page stitched by record id
./.venv/bin/scrapy crawl rover -a list=mre -a details=1
```

Output lands in `output/`:

* `output/<list>_list.json` — the grid rows
* `output/<list>_details.json` — the parsed detail pages (only with `-a details=1`)

### Spider arguments

| arg | default | meaning |
|---|---|---|
| `list` | `mre` | `sev`, `mre`, `vta`, `avv`, `cta`, `raw`, `tf` |
| `details` | `0` | `1` also fetches each detail page (`sev` and `mre` only) |
| `page_size` | `50` | rows per grid request |
| `max_pages` | `0` | stop after N pages; `0` = all |

## Stitching list → detail

Each list row's `Id` **is** the GUID in the detail URL, so no matching logic is
needed:

```
MRE-000001 → 2cb61393-ce5b-ec11-a305-0050569e60b7
           → /PublishedApprovals/ModelReportDetails/?id=2cb61393-ce5b-ec11-a305-0050569e60b7
```

Detail items also carry `_links`, which picks up the underlying SEV approval and
each Model Report Scope version (`MREDescriptorWorkInstruction?id=…&apprversionid=…`)
if you want to crawl a level deeper.

## Pairing SEV → MRE

Each register holds half of what an inspector needs. A **SEV** entry says a variant
may be imported, and why (the criterion), for which build dates — and sometimes
narrows that further in free text. A **Model Report** says a registered workshop can
modify that model to comply with the ADRs, for which build dates, to what level of
compliance; it also publishes its approval holder and their contact details.

`rover/pair.py` joins the two and lays the facts side by side. It **does not decide
eligibility**: no verdict, no pass/fail, and the two build-date ranges are never
intersected. The inspector reads the criteria and decides.

```bash
./.venv/bin/scrapy crawl rover -a list=sev -a details=1
./.venv/bin/scrapy crawl rover -a list=mre -a details=1
./.venv/bin/python -m rover.pair
```

Both detail crawls are **required**: `SEVCriterion`, `SEVVariant`, `SEVVariantDetails`
and the full SEV build-date range exist only on SEV detail pages, and the SEV→MRE link
exists only on MRE detail pages. Pairing is re-runnable without re-crawling.

### The join is published, not guessed

Every MRE detail page links the SEV approval(s) it rests on, so `_links` carries an
authoritative edge — no fuzzy matching. It is **many-to-many**: one report can cite
several SEVs (usually variants of one vehicle), and several workshops can hold reports
against one SEV. The output is therefore a join table, one row per SEV × MRE pair.

The approval holder is **not** matched against the RAW or AVV registers. An early version
did, and it was wrong: 664 of 926 reports are held by an entity in neither register,
because **holding a Model Report is its own approval type** — not a workshop
registration. `SYDNEY AVV PTY LTD` alone holds 296 reports and is in neither. The holder
name and contact details published on the report are carried through as-is.

### Output

`output/pairs.json` — one row per pair, each carrying the whole criteria set for a
human to read:

* **SEV side** — criterion, variant, model code(s), category, build date range (verbatim
  and parsed), expiry, under-review flag, and `variant_details` **verbatim**.
* **MRE side** — build date range, compliance level, status, post-modification category,
  source market, work instruction id, typical VIN, scope version count, approval holder.
* **Holder** — approval holder name and the contact details published on the report.
* **`search`** — a normalised haystack plus `model_codes` and `vin_patterns`, so a page
  can match a typed chassis code as a substring or a full VIN against the pattern.

`output/coverage.json` — what the dataset does and does not cover (completeness, not
judgement): `sev_without_model_report` (on the register, but no report cites it, so there
is no workshop to show), `unresolved_sev_links`, `mre_without_sev_link`, and a summary with the
criteria and compliance levels seen. `pair.py` warns when a feed looks truncated,
so an interrupted crawl is not mistaken for a register full of unpaired entries.

## The lookup page

`rover/page.py` builds a single self-contained HTML file from `pairs.json` — the tool
an inspector actually uses:

```bash
./.venv/bin/python -m rover.page          # -> output/rover_lookup.html
```

Search by chassis or model code, full VIN, make, model, workshop or approval number.
Results are grouped by SEV approval, because that is the shape of the decision: one
import eligibility, with the workshops holding a Model Report for it underneath.

* **Chassis codes** match as substrings, so `AHR20` finds the entry whose typical VIN is
  `6XXXXAHR20XXXXXXX`. A whole-word match ranks above a match inside a longer word, so
  `LFA` returns the Lexus before every *WeLFAre* body type.
* **A full VIN** (11+ characters) is tested against the register's own specimen VINs,
  whose `X`/`Z`/`#` placeholders become wildcards.
* **The build date filter is a range** — from and to, either side open. It keeps entries
  whose published range *overlaps* the one typed, and keeps entries that publish no range,
  so nothing is hidden by missing data.
* **Every published record is searchable**, in one of three shapes: a SEV approval with
  the Model Reports that cite it underneath; a SEV approval no report cites, which says
  so; or a Model Report shown on its own because the SEV approval it names is not in the
  register (withdrawn or superseded) or it links none at all. Nothing published is left
  unfindable.
* **Each report shows its full detail** — level of compliance in the register's own
  wording, build date range, post-modification category, model report type, source
  market, typical VIN, work instruction id, scope version count, the approval holder with
  their published contact details, and a link to the report on ROVER.

The page states the criteria and stops. It shows the SEV and Model Report build-date
ranges side by side and never intersects them, prints the variant-details text in full
where one exists, and computes no verdict anywhere. Re-run the crawls and the two
commands to refresh it.

### The structured build date range is not the whole story

Build date is the main range criterion — both registers key on it — but it only means
something once the variant is pinned down, and the SEV register's free-text **Variant
details** routinely narrows eligibility below `SEVBDR`. 11 of 25 sampled SEVs carried one:

```
Eligible build date range limited to 1/03/2010 to 20/07/2010 ONLY
SEVS eligibility restricted to USF 40 and USF 41 (2WD) with build date range of 1/09/2006 to 30/04/2007
2 door, K20A series motor, ONLY.
```

So the text is reproduced verbatim on every pair, `has_restriction_note` flags it for
attention, and any dates found in it are extracted into `restriction_dates_in_text`
**for display only** — the structured range is left untouched and nothing is computed
from either. A restriction about trim, drivetrain or engine cannot be applied
mechanically at all, which is the main reason the verdict is the inspector's.

The compliance level itself is a list-grid field with four published values:
`Complies`, `Substantially Complies - Minor and Inconsequential non-compliance`, the
rarer `Substantially Complies to an extent that makes it suitable for use on a public
road in Australia`, and blank. Beside it, some reports publish **`rvr_compliancenotes`**
("Compliance level notes"), which names the actual ADR:

```
Vehicle Substantially Complies with ADR 79/04. Using Japanese standard JC08 for compliance.
```

That field, and `rvr_additionalinformationpublishedmodelreport` ("Model Report notes",
which carries the series and engine), live in **section blocks** — `<div class="ls">`
with an `<h3 class="lsh">` heading — rather than in the table rows the rest of the page
uses. `parse_detail` sweeps up every id'd value div after the row pass and takes its
label from the enclosing section heading, so both layouts are captured. Deeper still,
the Model Report Scope and Vehicle Specification pages
(`MREDescriptorWorkInstruction`, `MREDescriptorVehicleScopeSEV`) hold the work
instruction number, pre/post-modification dimensions, body shape, tyre and rim sizes and
photographs — engineering specification, not per-ADR compliance criteria.

## The lookup page

`rover/page.py` builds a single self-contained HTML file from `pairs.json` — the tool
an inspector actually uses:

```bash
./.venv/bin/python -m rover.page          # -> output/rover_lookup.html
```

Search by chassis or model code, full VIN, make, model, workshop or approval number.
Results are grouped by SEV approval, because that is the shape of the decision: one
import eligibility, with the workshops holding a Model Report for it underneath.

* **Chassis codes** match as substrings, so `AHR20` finds the entry whose typical VIN is
  `6XXXXAHR20XXXXXXX`. A whole-word match ranks above a match inside a longer word, so
  `LFA` returns the Lexus before every *WeLFAre* body type.
* **A full VIN** (11+ characters) is tested against the register's own specimen VINs,
  whose `X`/`Z`/`#` placeholders become wildcards.
* **The build date filter is a range** — from and to, either side open. It keeps entries
  whose published range *overlaps* the one typed, and keeps entries that publish no range,
  so nothing is hidden by missing data.
* **Every published record is searchable**, in one of three shapes: a SEV approval with
  the Model Reports that cite it underneath; a SEV approval no report cites, which says
  so; or a Model Report shown on its own because the SEV approval it names is not in the
  register (withdrawn or superseded) or it links none at all. Nothing published is left
  unfindable.
* **Each report shows its full detail** — level of compliance in the register's own
  wording, build date range, post-modification category, model report type, source
  market, typical VIN, work instruction id, scope version count, the approval holder with
  their published contact details, and a link to the report on ROVER.

The page states the criteria and stops. It shows the SEV and Model Report build-date
ranges side by side and never intersects them, prints the variant-details text in full
where one exists, and computes no verdict anywhere. Re-run the crawls and the two
commands to refresh it.

### The structured build date range is not the whole story

Build date is the main range criterion — both registers key on it — but it only means
something once the variant is pinned down, and the SEV register's free-text **Variant
details** routinely narrows eligibility below `SEVBDR`. 11 of 25 sampled SEVs carried one:

```
Eligible build date range limited to 1/03/2010 to 20/07/2010 ONLY
SEVS eligibility restricted to USF 40 and USF 41 (2WD) with build date range of 1/09/2006 to 30/04/2007
2 door, K20A series motor, ONLY.
```

So the text is reproduced verbatim on every pair, `has_restriction_note` flags it for
attention, and any dates found in it are extracted into `restriction_dates_in_text`
**for display only** — the structured range is left untouched and nothing is computed
from either. A restriction about trim, drivetrain or engine cannot be applied
mechanically at all, which is the main reason the verdict is the inspector's.

There is **no compliance-notes field anywhere in the register**: `rvr_levelofcompliance`
is a list-grid-only grade with no notes beside it, and no detail page names the ADRs
involved — 17 field labels across 611 detail pages, none of them about compliance. The
grade's own wording is the whole of it, and it takes one of three values:
`Complies`, `Substantially Complies - Minor and Inconsequential non-compliance`, and
the rarer `Substantially Complies to an extent that makes it suitable for use on a
public road in Australia`. The page prints it in full rather than abbreviating it. One level deeper, the Model Report Scope and Vehicle Specification pages
(`MREDescriptorWorkInstruction`, `MREDescriptorVehicleScopeSEV`) hold the work
instruction number, pre/post-modification dimensions, body shape, tyre and rim sizes and
photographs — engineering specification, not per-ADR compliance criteria.

## Deployment

The whole thing is one periodic job and one static file: no server-side code, no
database. `.github/workflows/refresh.yml` runs daily at 16:00 UTC (about 02:00–03:00 in
eastern Australia, when the service is quiet), and can also be started by hand from the
Actions tab.

Each run:

1. runs the parser and pairing tests **before** crawling, so a broken build fails in
   seconds rather than after 35 minutes of requests;
2. crawls the SEVs Register and the Model Reports register with details
   (~35 minutes, ~1,550 requests — SEV 12 min / 599 requests, MRE 22 min / 948);
3. pairs them, then runs `scripts/check_fresh.py`, which **refuses to publish a short
   crawl**. Scrapy writes its feed as it goes, so an interrupted run leaves a valid JSON
   file holding a fraction of the register; publishing that would show "no model report"
   for vehicles that have one. The guard fails the build if either register comes back
   below 95% of its baseline or the detail count does not match the list count;
4. builds `site/index.html` and runs the page's own test suite against the exact file
   that will ship;
5. publishes to GitHub Pages.

`concurrency` keeps two crawls from ever overlapping, and never cancels one midway.

### First-time setup

```bash
git remote add origin git@github.com:<you>/<repo>.git
git push -u origin main
```

Then in the repository: **Settings → Pages → Source: GitHub Actions**. The first run can
be triggered from **Actions → Refresh ROVER lookup → Run workflow**.

### Running it locally

`make` mirrors what CI does:

```bash
make install     # venv + dependencies
make test        # the three suites
make refresh     # crawl, pair, check, build  (~35 min)
make serve       # http://127.0.0.1:8765/rover_lookup.html
```

### Before you make the site public

* **A GitHub Pages site is public**, including one built from a private repo (private
  Pages needs Enterprise). The page carries published register data only — approval
  holders' phone numbers and email addresses are deliberately not embedded in it — but
  `output/pairs.json` does contain them, which is why the workflow publishes only
  `site/index.html` and never the JSON.
* Check the department's terms for republishing ROVER data before putting it on a public
  domain.
* Keep the throttling in `rover/settings.py` as it is. A daily refresh is already ~1,550
  requests a day against a government service.

## Things to know

* **Responses are enormous.** Dataverse ships its full attribute metadata with
  every record — roughly 250 KB per row, so a 50-row page is 10–15 MB on the
  wire. `flatten()` throws the metadata away immediately, and `settings.py`
  lifts Scrapy's download size caps so the responses aren't dropped. Expect a
  full MRE crawl to pull a few hundred MB even though the JSON it writes is small.
* **Live counts at time of writing:** SEV 584 rows, MRE 926 rows.
* Values are kept as the portal displays them (`17/10/2026`), with the raw
  Dataverse value alongside under `<field>__raw` (`2026-10-17T00:00:00Z`) where
  the two differ.
* Throttling is deliberately conservative (2 concurrent, 1 s delay,
  AutoThrottle on). This is a government service — please leave it that way.
* If a token goes stale mid-crawl the portal answers with HTML; the spider
  detects that and re-fetches a token rather than failing.

## Offline tests

```bash
./.venv/bin/python tests/test_offline.py
./.venv/bin/python tests/test_pairing.py
node tests/test_page.js output/rover_lookup.html    # optional, needs node
```

Checks run over fixtures that mirror the real markup, JSON shapes and value formats —
including variant-details wording copied verbatim from the register.
`test_offline.py` covers config extraction, request construction, paging, flattening and
detail parsing; `test_pairing.py` covers date and name normalisation, build-range
intersection, prose build-date restrictions, the many-to-many fanout, every blocker
in isolation, and each section of the coverage report. Neither needs network or pytest.

`tests/test_page.js` is optional and needs node (no packages) plus a generated page. It
evaluates the page's own script in a stub DOM and drives the real `filter()` and
`render()` — the search ranking, the build-date range overlap and the VIN matching are
tested as shipped, not reimplemented.
