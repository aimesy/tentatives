// node worker/site/build.mjs
// Assembles the viewer Worker's static assets in worker/site/dist/ from site/
// and checks them. Left out: site/data/ (older county files; the viewer reads
// data only through the tentatives-data Worker, and a file here would be
// public without the origin check or the rate limit), the GitHub Pages CNAME
// and the static check script. Added: robots.txt, the policy Amy approved for
// her sites (amyc.us serves the same file), copied unchanged from here. Run
// update-site-counties.py first so counties.json lists every county in data/.

import assert from "node:assert/strict";
import { copyFileSync, cpSync, existsSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const SITE = fileURLToPath(new URL("../../site/", import.meta.url));
const DIST = fileURLToPath(new URL("./dist/", import.meta.url));
const ROBOTS = fileURLToPath(new URL("./robots.txt", import.meta.url));
const LEFT_OUT = new Set(["data", "CNAME", "check-static.mjs"]);
// Workers Free plan, static assets: files per Worker version, bytes per file.
const MAX_FILES = 20000;
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const DATA_WORKER = "https://tentatives-data.amyc.us/";

rmSync(DIST, { recursive: true, force: true });
cpSync(SITE, DIST, {
  recursive: true,
  filter: (src) => {
    const rel = relative(SITE, src);
    if (!rel) return true;
    const top = rel.split(sep)[0];
    return !LEFT_OUT.has(top) && !top.startsWith(".");
  },
});
assert.equal(existsSync(join(DIST, "robots.txt")), false, "site/robots.txt would compete with worker/site/robots.txt");
copyFileSync(ROBOTS, join(DIST, "robots.txt"));
const packager = fileURLToPath(new URL("../../.github/scripts/package_extension.py", import.meta.url));
execFileSync(process.env.PYTHON || (process.platform === "win32" ? "python" : "python3"), [packager, "--output", join(DIST, "downloads")], { stdio: "inherit" });
for (const name of ["tentatives-extension.zip", "tentatives-extension-chrome.zip", "tentatives-extension-firefox.zip"]) {
  assert.ok(existsSync(join(DIST, "downloads", name)), `${name} must be publicly downloadable`);
}

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    return e.isDirectory() ? walk(p) : [p];
  });
}

const files = walk(DIST).map((p) => ({ rel: relative(DIST, p).split(sep).join("/"), bytes: statSync(p).size }));
assert.ok(files.length > 0, "dist/ is empty");
assert.ok(files.length <= MAX_FILES, `${files.length} files; a Worker version holds at most ${MAX_FILES}`);
for (const f of files) {
  assert.ok(f.bytes <= MAX_FILE_BYTES, `${f.rel} is ${f.bytes} bytes; a static asset may be at most ${MAX_FILE_BYTES}`);
  assert.doesNotMatch(f.rel, /\.parquet$|^data\/|^archive\//, `${f.rel} must come through the data Worker, not the viewer's assets`);
}
assert.equal(existsSync(join(DIST, "CNAME")), false);
const robots = readFileSync(join(DIST, "robots.txt"));
assert.ok(robots.equals(readFileSync(ROBOTS)), "robots.txt must be published unchanged");
assert.match(robots.toString("utf8"), /^Content-Signal: search=yes, ai-train=no$/m, "robots.txt must carry the approved content signal");

const index = readFileSync(join(DIST, "index.html"), "utf8");
const app = readFileSync(join(DIST, "app.js"), "utf8");
assert.match(index, /connect-src [^;"]*https:\/\/tentatives-data\.amyc\.us[;\s]/, "the page policy must let the viewer reach the data Worker");
assert.ok(app.includes(`const DATA_WORKER = "${DATA_WORKER}";`), "app.js must read data through the data Worker");
const counties = JSON.parse(readFileSync(join(DIST, "counties.json"), "utf8"));
assert.ok(Array.isArray(counties) && counties.length > 0, "counties.json must list the counties");
for (const c of counties) assert.match(String(c.slug), /^[a-z0-9-]+$/, `county slug ${c.slug} would not match the data Worker's paths`);

const total = files.reduce((n, f) => n + f.bytes, 0);
console.log(`Viewer assets ready in worker/site/dist: ${files.length} files, ${total} bytes, ${counties.length} counties.`);
