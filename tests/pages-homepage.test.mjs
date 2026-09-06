import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const indexHtml = await readFile(new URL("../pages/index.html", import.meta.url), "utf8");
const appJs = await readFile(new URL("../pages/app.js", import.meta.url), "utf8");
const stylesCss = await readFile(new URL("../pages/styles.css", import.meta.url), "utf8");

// Living Press 版面骨架
assert.match(indexHtml, /id="home-view"/, "index.html should include a homepage view");
assert.match(indexHtml, /id="reader-view"/, "index.html should wrap the report reader in a reader view");
assert.match(indexHtml, /id="read-latest-btn"/, "homepage should expose a read-latest action");
assert.match(indexHtml, /id="recent-reports-list"/, "homepage should expose a recent reports list");
assert.match(indexHtml, /id="home-link"/, "header brand area should expose a home link");
assert.match(indexHtml, /id="search-btn"/, "utility bar should expose a search action");
assert.match(indexHtml, /id="theme-toggle"/, "utility bar should expose a theme toggle");
assert.match(indexHtml, /id="report-count"/, "utility bar should expose an edition counter");
assert.match(indexHtml, /github\.com\/cookiesheep\/csbaoyan-ribao/, "utility bar should link to the GitHub repository");

assert.match(appJs, /function\s+showHomeView\s*\(/, "app.js should render the no-hash homepage state");
assert.match(appJs, /function\s+showReaderView\s*\(/, "app.js should render the report reader state");
assert.match(appJs, /function\s+renderHomeView\s*\(/, "app.js should populate homepage data from the manifest");
assert.match(appJs, /function\s+extractOverview\s*\(/, "app.js should extract overview text from report markdown");
assert.match(appJs, /function\s+loadRecentReportSummaries\s*\(/, "app.js should load recent report summaries for the homepage");
assert.match(appJs, /replace\(\/\^\(\[-\+\*\]\|\\d\+\[\.\)\]\)\\s\+\/,\s*['"]['"]\)/, "overview extraction should strip markdown list markers");
assert.match(appJs, /const\s+target\s*=\s*getHashDate\(\)/, "manifest loading should not force a latest-date hash");
assert.match(appJs, /catch \(err\) \{\s*console\.error\(err\);\s*showReaderView\(\);/s, "manifest load failure should reveal the reader error state");

assert.match(stylesCss, /\.home-view\b/, "styles.css should style the homepage view");
assert.match(stylesCss, /\.archive-list\b/, "styles.css should style the archive list");

// 编辑部透明度：付印工单 / 原话引用 / 印房页
assert.match(indexHtml, /id="pressroom-view"/, "index.html should include a pressroom view");
assert.match(indexHtml, /href="#pressroom"/, "utility bar should link to the pressroom");
assert.match(indexHtml, /id="home-sift-count"/, "homepage sift card should expose a cumulative counter");
assert.match(indexHtml, /id="pt-raw"/, "pressroom totals should expose a raw-messages counter");
assert.match(indexHtml, /id="pt-dropped"/, "pressroom totals should expose a dropped counter");
assert.match(indexHtml, /id="pt-quotes"/, "pressroom totals should expose a quotes counter");
assert.match(indexHtml, /id="pt-editions"/, "pressroom totals should expose an editions counter");
assert.match(indexHtml, /id="pressroom-back-btn"/, "pressroom should expose a back action");
assert.match(indexHtml, /class="press-flow-list"/, "pressroom should render the pipeline flow list");

assert.match(appJs, /function\s+fetchStats\s*\(/, "app.js should fetch per-issue stats JSON");
assert.match(appJs, /function\s+makePrintDocket\s*\(/, "app.js should render a print docket from stats");
assert.match(appJs, /function\s+decorateSourceQuotes\s*\(/, "app.js should decorate source quotes in the DOM");
assert.match(appJs, /function\s+showPressroomView\s*\(/, "app.js should render the pressroom view");
assert.match(appJs, /function\s+loadPressTotals\s*\(/, "app.js should load cumulative stats summary");
assert.match(appJs, /target\s*===\s*["']pressroom["']/, "hash routing should handle #pressroom");
assert.ok(appJs.includes("data/stats/"), "stats fetch should target pages/data/stats/");

assert.match(stylesCss, /\.print-docket\b/, "styles.css should style the print docket");
assert.match(stylesCss, /\.docket-detail\b/, "styles.css should style the docket detail rows");
assert.match(stylesCss, /\.src-quote\b/, "styles.css should style source-quote spans");
assert.match(stylesCss, /\.pressroom-view\b/, "styles.css should style the pressroom view");
assert.match(stylesCss, /\.press-flow-list\b/, "styles.css should style the press flow list");
assert.match(stylesCss, /\.press-totals\b/, "styles.css should style the press totals grid");

// 来访统计：独立读者计数（发行量）
assert.match(indexHtml, /id="home-reader-count"/, "homepage front-stats should expose a readers card");
assert.match(indexHtml, /id="pt-readers"/, "pressroom totals should expose a readers card");
assert.match(appJs, /function\s+fetchReaderCount\s*\(/, "app.js should fetch the visitor count");
assert.match(appJs, /["']api\/count["']/, "reader count should POST the local counter endpoint");
assert.match(stylesCss, /repeat\(5,\s*1fr\)/, "press totals grid should hold a fifth card");

console.log("pages static assertions passed");
