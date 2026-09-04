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
  /https:\/\/cdn\.jsdelivr\.net\/gh\/aimesy\/themes@([0-9a-f]{40})\/src\/(theme\.css|theme-bar\.css|bug-report\.css|theme\.js|bug-report\.js)/g,
)];
const allSharedThemeMatches = [...indexSource.matchAll(
  /https:\/\/cdn\.jsdelivr\.net\/gh\/aimesy\/themes[^"' \s>]*/g,
)];

assert.equal(sharedThemeMatches.length, sharedThemeAssets.size, "shared theme asset set must contain exactly five pinned assets");
assert.equal(allSharedThemeMatches.length, sharedThemeAssets.size, "unexpected shared theme asset reference remains");
assert.deepEqual(
  new Set(sharedThemeMatches.map((match) => match[2])),
  sharedThemeAssets,
  "shared theme asset set is incomplete or duplicated",
);
assert.equal(new Set(sharedThemeMatches.map((match) => match[1])).size, 1, "shared theme assets must use one commit SHA");
assert.doesNotMatch(indexSource, /aimesy\/themes(?:\/|@(master|main|latest)\/)/i, "mutable or unversioned shared theme reference remains");
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

console.log("Viewer integration checks passed.");
