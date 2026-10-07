import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const indexSource = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const appSource = readFileSync(new URL("./app.js", import.meta.url), "utf8");
const stylesSource = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const sharedThemeAssets = new Set([
  "theme.css",
  "theme-bar.css",
  "bug-report.css",
  "theme.js",
  "bug-report.js",
]);
const sharedThemeMatches = [...indexSource.matchAll(
  /https:\/\/aimesy\.github\.io\/themes\/src\/(theme\.css|theme-bar\.css|bug-report\.css|theme\.js|bug-report\.js)/g,
)];
const allSharedThemeMatches = [...indexSource.matchAll(
  /https:\/\/aimesy\.github\.io\/themes[^"' \s>]*/g,
)];

assert.equal(sharedThemeMatches.length, sharedThemeAssets.size, "shared theme asset set must contain exactly five live assets");
assert.equal(allSharedThemeMatches.length, sharedThemeAssets.size, "unexpected shared theme asset reference remains");
assert.deepEqual(
  new Set(sharedThemeMatches.map((match) => match[1])),
  sharedThemeAssets,
  "shared theme asset set is incomplete or duplicated",
);
assert.doesNotMatch(indexSource, /cdn\.jsdelivr\.net\/gh\/aimesy\/themes/i, "shared theme must load live from aimesy.github.io/themes, not a jsDelivr pin");
assert.match(indexSource, /script-src [^;"]*https:\/\/aimesy\.github\.io[;\s"]/, "CSP script-src must allow the shared theme host");
assert.match(indexSource, /style-src [^;"]*https:\/\/aimesy\.github\.io[;\s"]/, "CSP style-src must allow the shared theme host");
assert.doesNotMatch(indexSource, /font-system\./, "unused shared font-system assets must not load");
assert.equal((indexSource.match(/\bdata-theme-toggle\b/g) || []).length, 1, "viewer must contain exactly one theme toggle");
assert.equal((indexSource.match(/\bamyc-theme-bar\b/g) || []).length, 1, "viewer must contain exactly one shared theme bar");
assert.ok(indexSource.indexOf('href="styles.css') < indexSource.indexOf("/src/theme.css"), "shared theme CSS must load after local viewer CSS");
assert.doesNotMatch(indexSource, />\s*[vV]\s*</, "viewer controls must use arrow glyphs, not the letter v");
assert.doesNotMatch(indexSource, />Excerpt</, "the redundant Excerpt column must stay removed");
assert.doesNotMatch(appSource, /col-text|label:\s*"Excerpt"|cell-clamp/);
assert.doesNotMatch(stylesSource, /\.col-text|\.cell-clamp|content:\s*" [vV^]"/);
assert.equal((indexSource.match(/class="col-filter-btn"/g) || []).length, 6);
assert.equal((indexSource.match(/class="caret">▾<\/span>/g) || []).length, 2);
assert.equal((appSource.match(/\.colSpan = 11;/g) || []).length, 2);
assert.match(indexSource, /id="county-load-status"[^>]*role="status"[^>]*aria-live="polite"/);
assert.match(indexSource, /id="county-load-progress"[^>]*aria-labelledby="county-load-label"/);
assert.match(appSource, /function selectedLoadState\(\)/);
assert.match(appSource, /function retryFailedCounties\(\)/);
assert.match(appSource, /Results appear as each county data file is ready\./);
assert.doesNotMatch(indexSource + appSource, /loading\.\.\.|Loading\.\.\./);
assert.doesNotMatch(indexSource + appSource, /id="stages"|setStage\(/);

// Data: the repository is private, so the viewer reads county files and PDF
// slices only through the tentatives-data Worker (worker/data/), which serves
// exactly the paths the viewer may ask for.
const workerSource = readFileSync(new URL("../worker/data/release.js", import.meta.url), "utf8");
assert.match(appSource, /const DATA_WORKER = "https:\/\/tentatives-data\.amyc\.us\/";/, "viewer must read data through the tentatives-data Worker");
const csp = /http-equiv="Content-Security-Policy"\s+content="([^"]+)"/.exec(indexSource)?.[1] || "";
const cspSources = (name) => (csp.split(";").map((d) => d.trim().split(/\s+/)).find((d) => d[0] === name) || []).slice(1);
assert.deepEqual(cspSources("connect-src"), ["'self'", "https://tentatives-data.amyc.us", "https://cloudflareinsights.com"], "CSP connect-src must allow the data Worker and Cloudflare Web Analytics, and nothing else");
assert.ok(cspSources("script-src").includes("https://static.cloudflareinsights.com"), "CSP script-src must allow the Cloudflare Web Analytics beacon");
assert.doesNotMatch(indexSource + appSource, /raw\.githubusercontent\.com|api\.github\.com|github\.com\/aimesy\/tentatives\/(?:blob|raw)\//, "viewer must not reach the private repository on GitHub directly");
assert.doesNotMatch(indexSource, /github\.com\/aimesy\/tentatives|aimesy\.github\.io\/sfsc\//, "public controls must not lead to private repositories or the retired SFSC site");
assert.match(indexSource, /href="mailto:me@amyc\.us\?subject=Tentatives%20bug%20report"/, "bug reports must reach the public contact");
assert.match(indexSource, /href="downloads\/tentatives-extension\.zip" download/, "Chrome extension must download from this site");
assert.match(indexSource, /href="downloads\/tentatives-extension-firefox\.zip" download/, "Firefox extension must download from this site");
assert.doesNotMatch(appSource, /DATA_ROOT_CANDIDATES|fetch\(`data\//, "the deployed viewer has no same-origin data");
const regexOf = (src, name) => new RegExp(`const ${name} = (\\/.+\\/);`).exec(src)?.[1];
assert.ok(regexOf(appSource, "DATA_PATH"), "app.js must define DATA_PATH");
assert.equal(regexOf(workerSource, "DATA_PATH"), regexOf(appSource, "DATA_PATH"), "worker/data/release.js must allow exactly the DATA_PATH values app.js asks for");
assert.match(workerSource, /export const REPO = "aimesy\/tentatives-data";/);
assert.match(appSource, /data\/\$\{county\.slug\}\/summary\.json/, "county browsing must use metadata summaries");
assert.match(appSource, /data\/\$\{row\.county\}\/rulings\/\$\{row\.ruling_id\}\.json/, "complete text must use the per-ruling route");
assert.doesNotMatch(appSource, /rulings\.parquet|parquetReadObjects/, "the viewer must never preload full county text");

console.log("Viewer integration checks passed.");
