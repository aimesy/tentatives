import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { classifyMotion } from "./motions.js";

const indexSource = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const appSource = readFileSync(new URL("./app.js", import.meta.url), "utf8");
const stylesSource = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

assert.doesNotMatch(indexSource, />\s*[vV]\s*</, "viewer controls must use arrow glyphs, not the letter v");
assert.doesNotMatch(indexSource, />Excerpt</, "the redundant Excerpt column must stay removed");
assert.doesNotMatch(appSource, /col-text|label:\s*"Excerpt"|cell-clamp/);
assert.doesNotMatch(stylesSource, /\.col-text|\.cell-clamp|content:\s*" [vV^]"/);
assert.equal((indexSource.match(/class="col-filter-btn"/g) || []).length, 6);
assert.equal((indexSource.match(/class="caret">▾<\/span>/g) || []).length, 2);
assert.equal((appSource.match(/\.colSpan = 12;/g) || []).length, 2);
assert.match(indexSource, /data-col="motion_category"/);
assert.match(indexSource, /data-col="motion_type"/);
assert.match(indexSource, /data-col="motion_caption"/);
assert.match(appSource, /motion_category: motion\.category/);
assert.match(appSource, /motion_caption: motionCaption/);
assert.match(indexSource, /id="county-load-status"[^>]*role="status"[^>]*aria-live="polite"/);
assert.match(indexSource, /id="county-load-progress"[^>]*aria-labelledby="county-load-label"/);
assert.match(appSource, /function selectedLoadState\(\)/);
assert.match(appSource, /function retryFailedCounties\(\)/);
assert.match(appSource, /Results appear as each county data file is ready\./);
assert.doesNotMatch(indexSource + appSource, /loading\.\.\.|Loading\.\.\./);
assert.doesNotMatch(indexSource + appSource, /id="stages"|setStage\(/);

assert.deepEqual(classifyMotion("Demurrer to First Amended Complaint"), {
  category: "Pleadings", type: "Demurrer", subtype: null,
});
assert.deepEqual(classifyMotion("Motion to Compel Further Responses to Special Interrogatories"), {
  category: "Discovery", type: "Compel Further Responses", subtype: null,
});
assert.deepEqual(classifyMotion("Motion for Summary Judgment or Summary Adjudication"), {
  category: "Dispositive",
  type: "Summary Judgment / Adjudication",
  subtype: "Combined Summary Judgment/Adjudication",
});
assert.deepEqual(classifyMotion("Request for Order re Child Custody and Parenting Time", "Family Law"), {
  category: "Family Law", type: "Child Custody / Visitation", subtype: null,
});
assert.deepEqual(classifyMotion("Petition to Appoint Successor Trustee", "Probate"), {
  category: "Probate", type: "Trustee Appointment / Removal", subtype: null,
});
assert.deepEqual(classifyMotion("", "Probate"), {
  category: "Probate", type: "Probate Matter", subtype: null,
});

console.log("Viewer integration checks passed.");
