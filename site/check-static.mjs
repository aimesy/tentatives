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

console.log("Viewer integration checks passed.");
