/*
 * Offline check of the lookup page's own search code.
 *
 * Loads a generated page, evaluates the script it ships with inside a stub
 * DOM, then drives the real filter() and render(). Nothing is reimplemented
 * here, so a bug in the page fails this test.
 *
 * Needs node (no packages) and a generated page:
 *     ./.venv/bin/python -m rover.page
 *     node tests/test_page.js output/rover_lookup.html
 */
const fs = require("fs");
const target = process.argv[2] || "output/rover_lookup.html";
const html = fs.readFileSync(target, "utf8");
const data = html.match(/<script id="data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const code = html.match(/<script>\n\(function \(\)[\s\S]*?\}\(\)\);\n<\/script>/)[0]
  .replace(/^<script>\n/, "").replace(/<\/script>\n?$/, "");

const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, value: "", textContent: "", innerHTML: "",
                            hidden: false, addEventListener(){}, focus(){} };
  return els[id];
}
els.data = { textContent: data.replace(/<\\\//g, "</") };
global.document = { getElementById: el };
global.window = {};
global.setTimeout = (fn) => fn();
global.clearTimeout = () => {};
global.Map = Map;

// expose filter() by wrapping the IIFE's own render call
eval(code.replace("render();\n}());", "window.__filter = filter;\n  window.__render = render;\n  render();\n}());"));
const filter = global.window.__filter, render = global.window.__render;

const entries = JSON.parse(els.data.textContent).entries;
let fails = 0;
function check(name, cond, extra) {
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra ? "  " + extra : ""));
  if (!cond) fails++;
}

// a SEV with a closed published range, to aim the filter at
const closed = entries.find(e => e.sev && e.sev.build_from && e.sev.build_to);
if (!closed) {
  console.log("no SEV in this data has a closed build range; nothing to filter against");
  process.exit(1);
}
const [m, y] = closed.sev.build_from.split("/").map(Number);
const key = (yy, mm) => ({ from: yy * 100 + mm, to: yy * 100 + mm });
const idOf = (e) => (e.sev && e.sev.approval) || (e.report && e.report.approval);
const modelOf = (e) => (e.sev && e.sev.model) || (e.report && e.report.model) || "";
const has = (list, ap) => list.some(e => idOf(e) === ap);

console.log(`range filter against ${closed.sev.approval} ${closed.sev.build_range_text}`);
check("inside the published range matches",
      has(filter("", key(y, m)), closed.sev.approval));
check("a range ending before it does not",
      !has(filter("", { from: null, to: (y - 20) * 100 + 1 }), closed.sev.approval));
check("a range starting after it does not",
      !has(filter("", { from: (y + 50) * 100 + 1, to: null }), closed.sev.approval));
check("an overlapping window matches",
      has(filter("", { from: (y - 1) * 100 + m, to: (y + 1) * 100 + m }), closed.sev.approval));
check("open-ended from matches", has(filter("", { from: null, to: y * 100 + m }), closed.sev.approval));
check("no range set returns everything", filter("", null).length === entries.length);
check("entries with no published range are kept",
      filter("", key(1990, 1)).every(e => true) &&
      filter("", key(1990, 1)).length > 0);

// text search still works through the same function, on a model code the
// current data actually carries
const probeCode = entries.reduce((found, e) => found ||
  (e.codes || []).find(c => /^[A-Z0-9]{4,}$/.test(c) &&
    filter(c, null).length < entries.length), null);
check("a model code to search for exists", !!probeCode, String(probeCode));
if (probeCode) {
  const chassis = filter(probeCode, null);
  check("text search narrows to the chassis code",
        chassis.length > 0 && chassis.length < entries.length &&
        chassis.every(e => JSON.stringify(e).indexOf(probeCode) !== -1),
        probeCode + ": " + chassis.length + " records");
  check("text + range combine",
        filter(probeCode, key(y, m)).length <= filter(probeCode, null).length);
}

// Ranking: a whole-word hit must outrank one that is only a substring.
// The probe comes from the data, because which models are on the register
// changes with every crawl.
const hay = (e) => e.haystack || "";
const wholeWord = (h, w) => new RegExp("(^| )" + w + "( |$)").test(h);
const probe = entries.map(e => modelOf(e).toUpperCase())
  .filter(w => /^[A-Z0-9]{3,}$/.test(w))
  .find(w => entries.some(e => wholeWord(hay(e), w)) &&
             entries.some(e => hay(e).indexOf(w) !== -1 && !wholeWord(hay(e), w)));
if (!probe) {
  console.log("  SKIP  ranking: no model is both a whole word and a substring");
} else {
  const ranked = filter(probe, null);
  const firstPartial = ranked.findIndex(e => !wholeWord(hay(e), probe));
  const lastWhole = ranked.reduce((at, e, i) => wholeWord(hay(e), probe) ? i : at, -1);
  check("ranking puts the whole word first",
        firstPartial === -1 || lastWhole < firstPartial,
        probe + ": " + (firstPartial === -1 ? "no partial hits" :
          String(firstPartial) + " whole-word hits then " +
          (ranked.length - firstPartial) + " partial") +
          ", top " + modelOf(ranked[0]));
}

// model reports with no SEV approval are entries in their own right
const lone = entries.filter(e => e.kind === "report");
check("lone model reports are present", lone.length > 0, String(lone.length));
if (lone.length) {
  const ap = lone[0].report.approval;
  check("a lone report is findable by its approval number", has(filter(ap, null), ap));
  check("a lone report carries its compliance level field",
        "compliance_level" in lone[0].report);
  check("a lone report survives sorting next to SEV entries",
        filter("", null).length === entries.length);
  const r = lone[0].report;
  if (r.build_from) {
    const [mm, yy] = r.build_from.split("/").map(Number);
    check("the date filter uses a lone report's own build range",
          has(filter("", { from: yy * 100 + mm, to: yy * 100 + mm }), ap));
    check("and excludes it when the window misses",
          !has(filter("", { from: (yy + 60) * 100 + 1, to: null }), ap));
  }
}

// render() must not throw with the fake DOM
render();
check("render() completes", typeof els.results.innerHTML === "string" && els.results.innerHTML.length > 0);
check("status line written", /of \d+ records/.test(els.status.innerHTML),
      els.status.innerHTML.slice(0, 80));

console.log(fails ? `\n${fails} FAILED` : "\nall checks passed");
process.exit(fails ? 1 : 0);
