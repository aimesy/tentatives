import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const indexSource = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const appSource = readFileSync(new URL("./app.js", import.meta.url), "utf8");
const stylesSource = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

assert.doesNotMatch(indexSource, />\s*[vV]\s*</, "viewer controls must use arrow glyphs, not the letter v");
assert.doesNotMatch(indexSource, />Excerpt</, "the redundant Excerpt column must stay removed");
assert.doesNotMatch(appSource, /col-text|label:\s*"Excerpt"|cell-clamp/);
assert.doesNotMatch(stylesSource, /\.col-text|\.cell-clamp|content:\s*" [vV^]"/);
assert.equal((indexSource.match(/class="col-filter-btn"/g) || []).length, 5);
assert.equal((indexSource.match(/class="caret">▾<\/span>/g) || []).length, 2);
assert.equal((appSource.match(/\.colSpan = 10;/g) || []).length, 2);
assert.match(indexSource, /id="county-load-status"[^>]*role="status"[^>]*aria-live="polite"/);
assert.match(indexSource, /id="county-load-progress"[^>]*aria-labelledby="county-load-label"/);
assert.match(appSource, /function selectedLoadState\(\)/);
assert.match(appSource, /function retryFailedCounties\(\)/);
assert.match(appSource, /Results appear as each county data file is ready\./);
assert.doesNotMatch(indexSource + appSource, /loading\.\.\.|Loading\.\.\./);
assert.doesNotMatch(indexSource + appSource, /id="stages"|setStage\(/);

console.log("Viewer integration checks passed.");
