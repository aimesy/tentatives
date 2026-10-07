// node worker/worker.test.mjs
// Unit checks for the tentatives-data Worker (worker/data/release.js) with a
// mocked env, a stub for the cached Release entrypoint and a mocked fetch.
// Adapted from aimesy/mfa's tests/worker.test.mjs.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { handleGateway, handleRelease, route, DATA_PATH, HOME_PATH, REPO, BRANCH, documentKey, OPEN_PATHS } from "./data/release.js";
import { checkGate } from "./data/gate.contract.mjs";

const SHA = "0123456789abcdef0123456789abcdef01234567";
const SITE = "https://tentatives.amyc.us";
const HOME = "https://amyc.us";
const BASE = "https://tentatives-data.amyc.us";
const ID = "3fa1b2c3d4e5f60718293a4b5c6d7e8f";
const PDF = `archive/el-dorado/rulings/3f/${ID}.pdf`;
const SUMMARY = "data/los-angeles/summary.json";
const TEXT = `data/el-dorado/rulings/${ID}.json`;

function limiter(allow = true) {
  const keys = [];
  return { keys, limit: async ({ key }) => { keys.push(key); return { success: allow }; } };
}

function env(extra = {}) {
  return { ALLOWED_ORIGINS: "https://tentatives.amyc.us https://amyc.us", RATE_LIMITER: limiter(), ...extra };
}

// Gateway with a stub Release entrypoint that records what it was sent.
async function gateway(path, { method = "GET", headers = {}, e = env(), reply } = {}) {
  const sent = [];
  const release = async (req) => {
    sent.push(req);
    return reply ? reply(req) : new Response("body", { headers: { "Content-Type": "application/pdf", "Cache-Control": "public, max-age=31536000, immutable" } });
  };
  const res = await handleGateway(new Request(`${BASE}${path}`, { method, headers }), e, { release, log: () => {} });
  return { res, sent };
}

// Release entrypoint with a mocked GitHub.
async function release(path, { headers = {}, method = "GET", e = {}, upstream } = {}) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return upstream ? upstream(url, init) : new Response(url.endsWith(".json") ? "[]" : "PAR1", { status: 200, headers: { "Content-Length": url.endsWith(".json") ? "2" : "4", ETag: '"abc"' } });
  };
  const res = await handleRelease(new Request(`${BASE}${path}`, { method, headers }), e, fetchImpl);
  return { res, calls };
}

// Repository and branch.
assert.equal(REPO, "aimesy/tentatives-data");
assert.equal(BRANCH, "master");

// Path allowlist: county files, ruling PDFs and LIVE.md, at a commit or master.
{
  assert.deepEqual(route(`/${SHA}/${SUMMARY}`), { kind: "file", ref: SHA, path: SUMMARY });
  assert.deepEqual(route(`/master/data/el-dorado/summary.json`), { kind: "file", ref: "master", path: "data/el-dorado/summary.json" });
  assert.deepEqual(route(`/${SHA}/${PDF}`), { kind: "file", ref: SHA, path: PDF });
  assert.deepEqual(route("/ref"), { kind: "ref" });
  assert.deepEqual(route("/master/LIVE.md"), { kind: "file", ref: "master", path: "LIVE.md" });
  assert.deepEqual(route(`/${SHA}/LIVE.md`), { kind: "file", ref: SHA, path: "LIVE.md" });
  for (const bad of [
    `/${SHA}/.github/workflows/site.yml`, `/${SHA}/README.md`, `/${SHA}/data/el-dorado/README.md`,
    `/${SHA}/data/el-dorado/rulings.csv`, `/${SHA}/data/el-dorado/rulings.parquet`, `/${SHA}/data/el-dorado/ruling-text/3f.json`, `/${SHA}/data/el-dorado/_viewer.json`, `/${SHA}/data/El-Dorado/rulings.parquet`, `/${SHA}/data/x/y/rulings.parquet`,
    `/${SHA}/data/../data/x/rulings.parquet`, `/${SHA}/data/%2e%2e/rulings.parquet`,
    `/${SHA}/archive/el-dorado/rulings/4f/${ID}.pdf`, // the folder must be the id's first two characters
    `/${SHA}/archive/el-dorado/rulings/3f/${ID.slice(1)}.pdf`, `/${SHA}/archive/el-dorado/rulings/3f/${ID.toUpperCase()}.pdf`,
    `/${SHA}/archive/el-dorado/3f/${ID}.pdf`, `/${SHA}/archive/el-dorado/captures.ndjson`, `/${SHA}/archive/el-dorado/rulings/3f/${ID}.docx`,
    `/${SHA}/archive/el-dorado/ocr/3f/${ID}.pdf`, `/${SHA}/site/app.js`, `/${SHA}/extension/manifest.json`,
    `/${SHA.toUpperCase()}/${SUMMARY}`, `/main/${SUMMARY}`, `/${SHA.slice(1)}/${SUMMARY}`, `/HEAD/${SUMMARY}`,
    "/", `/${SUMMARY}`, `/${SHA}/`, `/${SHA}/data`, `/master/${SUMMARY}/x`,
    "/LIVE.md", "/master/live.md", "/master/data/LIVE.md", "/master/LIVE.md/x", "/master/README.md",
  ]) assert.equal(route(bad), null, `${bad} must be refused`);
  assert.equal(DATA_PATH.test(SUMMARY), true);
  assert.equal(DATA_PATH.test("LIVE.md"), false, "the viewer never asks for LIVE.md");
  assert.equal(HOME_PATH.test("LIVE.md"), true);
}

// Unknown or missing origin: 403, and the Release entrypoint is never called.
{
  for (const headers of [{}, { Origin: "https://evil.example" }, { Origin: "null" }, { Origin: "https://aimesy.github.io" }, { Referer: "https://evil.example/tentatives/" }, { Origin: "https://evil.example", Referer: `${SITE}/` }]) {
    const { res, sent } = await gateway(`/${SHA}/${SUMMARY}`, { headers });
    assert.equal(res.status, 403, JSON.stringify(headers));
    assert.equal(sent.length, 0);
    assert.equal(res.headers.get("Access-Control-Allow-Origin"), null);
    assert.equal(res.headers.get("X-Robots-Tag"), "noindex");
  }
}

// Allowed by Origin (fetch) or by Referer (a PDF slice opened in a new tab); CORS on the answer.
{
  const { res, sent } = await gateway(`/${SHA}/${SUMMARY}`, { headers: { Origin: SITE } });
  assert.equal(res.status, 200);
  assert.equal(sent.length, 1);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), SITE);
  assert.match(res.headers.get("Vary"), /Origin/);
  assert.equal(res.headers.get("Access-Control-Expose-Headers"), "Content-Range, Content-Length, Accept-Ranges, Retry-After, X-Check, X-Limit, X-Tentatives-Session, X-Trusted-Key");
  assert.equal(res.headers.get("X-Robots-Tag"), "noindex");
  assert.equal(await res.text(), "body");

  const viaReferer = await gateway(`/${SHA}/${PDF}`, { headers: { Referer: `${SITE}/?county=el-dorado&r=x` } });
  assert.equal(viaReferer.res.status, 200);
  assert.equal(viaReferer.res.headers.get("Access-Control-Allow-Origin"), SITE);

  const home = await gateway("/master/LIVE.md?v=1759500000000", { headers: { Origin: HOME } });
  assert.equal(home.res.status, 200);
  assert.equal(home.res.headers.get("Access-Control-Allow-Origin"), HOME);
  assert.equal(home.sent[0].url, `${BASE}/master/LIVE.md`, "the home page's cache-busting query never reaches the cache key");
  for (const sub of ["https://www.amyc.us", "http://amyc.us", "https://amyc.us.evil.example"]) {
    assert.equal((await gateway("/master/LIVE.md", { headers: { Origin: sub } })).res.status, 403, sub);
  }

  const kept = await gateway(`/${SHA}/${SUMMARY}`, { headers: { Origin: SITE }, reply: () => new Response("x", { headers: { Vary: "Accept-Encoding" } }) });
  assert.equal(kept.res.headers.get("Vary"), "Accept-Encoding, Origin");
}

// Query stripping and Range forwarding: the inner request carries the path and Range only.
{
  const { sent } = await gateway(`/${SHA}/${SUMMARY}?cachebust=1&token=x`, {
    headers: { Origin: SITE, Range: "bytes=0-262143", Cookie: "a=b", Authorization: "Bearer nope", "Cache-Control": "no-cache" },
  });
  const inner = sent[0];
  assert.equal(inner.url, `${BASE}/${SHA}/${SUMMARY}`);
  assert.deepEqual([...inner.headers.keys()], ["range"]);
  assert.equal(inner.headers.get("Range"), "bytes=0-262143");
  assert.equal(inner.method, "GET");

  const plain = await gateway(`/${SHA}/${SUMMARY}`, { headers: { Origin: SITE, Accept: "*/*" } });
  assert.deepEqual([...plain.sent[0].headers.keys()], []);

  const head = await gateway(`/${SHA}/${SUMMARY}`, { method: "HEAD", headers: { Origin: SITE } });
  assert.equal(head.sent[0].method, "HEAD");
}

// A ranged answer keeps its status and Content-Range through the gateway.
{
  const { res } = await gateway(`/${SHA}/${SUMMARY}`, {
    headers: { Origin: SITE, Range: "bytes=0-3" },
    reply: () => new Response("PAR1", { status: 206, headers: { "Content-Range": "bytes 0-3/72966744", "Content-Length": "4" } }),
  });
  assert.equal(res.status, 206);
  assert.equal(res.headers.get("Content-Range"), "bytes 0-3/72966744");
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), SITE);
  assert.equal(await res.text(), "PAR1");
}

// Paths outside the allowlist: 404 without reaching GitHub.
{
  const { res, sent } = await gateway(`/${SHA}/.git/config`, { headers: { Origin: SITE } });
  assert.equal(res.status, 404);
  assert.equal(sent.length, 0);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), SITE);
  assert.equal(res.headers.get("Cache-Control"), "no-store");
}

// Rate limit: per CF-Connecting-IP; over the limit, 429 with Retry-After and CORS so the viewer sees it.
{
  const e = env({ RATE_LIMITER: limiter(false) });
  const { res, sent } = await gateway(`/${SHA}/${SUMMARY}`, { headers: { Origin: SITE, "CF-Connecting-IP": "203.0.113.9" }, e });
  assert.equal(res.status, 429);
  assert.equal(sent.length, 0);
  assert.equal(res.headers.get("Retry-After"), "60");
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), SITE);
  assert.equal(res.headers.get("Access-Control-Expose-Headers"), "Content-Range, Content-Length, Accept-Ranges, Retry-After, X-Check, X-Limit, X-Tentatives-Session, X-Trusted-Key");
  assert.deepEqual(e.RATE_LIMITER.keys, ["203.0.113.9"]);

  const ok = env();
  await gateway(`/${SHA}/${SUMMARY}`, { headers: { Origin: SITE, "CF-Connecting-IP": "198.51.100.4" }, e: ok });
  assert.deepEqual(ok.RATE_LIMITER.keys, ["198.51.100.4"]);

  // A refused origin never spends the caller's limit.
  const refused = env();
  await gateway(`/${SHA}/${SUMMARY}`, { headers: { Origin: "https://evil.example", "CF-Connecting-IP": "198.51.100.5" }, e: refused });
  assert.deepEqual(refused.RATE_LIMITER.keys, []);
}

// OPTIONS preflight: allowed origin gets Range; unknown origin gets 403.
{
  const { res, sent } = await gateway(`/${SHA}/${SUMMARY}`, {
    method: "OPTIONS", headers: { Origin: SITE, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "range" },
  });
  assert.equal(res.status, 204);
  assert.equal(sent.length, 0);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), SITE);
  assert.match(res.headers.get("Access-Control-Allow-Headers"), /Range/);
  assert.match(res.headers.get("Access-Control-Allow-Methods"), /GET/);
  assert.match(res.headers.get("Vary"), /Origin/);
  const denied = await gateway(`/${SHA}/${SUMMARY}`, { method: "OPTIONS", headers: { Origin: "https://evil.example" } });
  assert.equal(denied.res.status, 403);
}

// Other methods are refused.
{
  const { res, sent } = await gateway(`/${SHA}/${SUMMARY}`, { method: "POST", headers: { Origin: SITE } });
  assert.equal(res.status, 405);
  assert.equal(sent.length, 0);
}

// robots.txt disallows everything, for anyone.
{
  const { res, sent } = await gateway("/robots.txt");
  assert.equal(res.status, 200);
  assert.equal(sent.length, 0);
  assert.equal(await res.text(), "User-agent: *\nDisallow: /\n");
  assert.equal(res.headers.get("X-Robots-Tag"), "noindex");
}

// Upstream: Authorization only when the token is set, User-Agent always, Range passed through.
{
  const withToken = await release(`/${SHA}/${SUMMARY}`, { e: { TENTATIVES_DATA_TOKEN: "t0ken" } });
  assert.equal(withToken.calls[0].url, `https://raw.githubusercontent.com/aimesy/tentatives-data/${SHA}/${SUMMARY}`);
  assert.equal(withToken.calls[0].init.headers.Authorization, "Bearer t0ken");
  assert.match(withToken.calls[0].init.headers["User-Agent"], /tentatives-data-worker/);

  const without = await release(`/${SHA}/${SUMMARY}`);
  assert.equal("Authorization" in without.calls[0].init.headers, false);

  const ranged = await release(`/${SHA}/${PDF}`, {
    headers: { Range: "bytes=262144-524287" },
    upstream: () => new Response("part", { status: 206, headers: { "Content-Range": "bytes 262144-524287/72966744", "Content-Length": "262144" } }),
  });
  assert.equal(ranged.calls[0].init.headers.Range, "bytes=262144-524287");
  assert.equal(ranged.res.status, 206);
  assert.equal(ranged.res.headers.get("Content-Range"), "bytes 262144-524287/72966744");
  assert.equal(ranged.res.headers.get("Content-Length"), "262144");
  assert.equal(ranged.res.headers.get("Accept-Ranges"), "bytes");

  const head = await release(`/${SHA}/${SUMMARY}`, { method: "HEAD" });
  assert.equal(head.calls[0].init.method, "HEAD");
  assert.equal(head.res.body, null);
}

// Cache headers: a commit is immutable, master is short; errors are never stored.
{
  const pinned = await release(`/${SHA}/${PDF}`);
  assert.equal(pinned.res.status, 200);
  assert.equal(pinned.res.headers.get("Cache-Control"), "public, max-age=31536000, immutable");
  assert.equal(pinned.res.headers.get("Content-Type"), "application/pdf");
  assert.equal(pinned.res.headers.get("ETag"), '"abc"');
  assert.equal(pinned.res.headers.get("Content-Length"), "4");
  assert.equal(pinned.res.headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal(pinned.res.headers.get("Content-Security-Policy"), null, "PDFs open in the browser's viewer");

  const head = await release(`/master/${SUMMARY}`);
  assert.equal(head.res.headers.get("Cache-Control"), "public, max-age=300");
  assert.equal(head.res.headers.get("Content-Type"), "application/json; charset=utf-8");
  assert.equal(head.res.headers.get("Content-Security-Policy"), "default-src 'none'; sandbox");

  const live = await release("/master/LIVE.md", { upstream: () => new Response("## LIVE\n", { status: 200 }) });
  assert.equal(live.calls[0].url, "https://raw.githubusercontent.com/aimesy/tentatives-data/master/LIVE.md");
  assert.equal(live.res.headers.get("Content-Type"), "text/plain; charset=utf-8");
  assert.equal(live.res.headers.get("Cache-Control"), "public, max-age=300");
  assert.equal(live.res.headers.get("Content-Security-Policy"), "default-src 'none'; sandbox");

  const missing = await release(`/${SHA}/${SUMMARY}`, { upstream: () => new Response("404: Not Found", { status: 404 }) });
  assert.equal(missing.res.status, 404);
  assert.equal(missing.res.headers.get("Cache-Control"), "no-store");
  const broken = await release(`/${SHA}/${SUMMARY}`, { upstream: () => new Response("", { status: 500 }) });
  assert.equal(broken.res.status, 502);
  assert.equal(broken.res.headers.get("Cache-Control"), "no-store");
  const down = await release(`/${SHA}/${SUMMARY}`, { upstream: () => { throw new Error("connect failed"); } });
  assert.equal(down.res.status, 502);
  assert.equal(down.res.headers.get("Cache-Control"), "no-store");
  const unsatisfiable = await release(`/${SHA}/${PDF}`, { upstream: () => new Response("", { status: 416, headers: { "Content-Range": "bytes */4" } }) });
  assert.equal(unsatisfiable.res.status, 416);
  assert.equal(unsatisfiable.res.headers.get("Content-Range"), "bytes */4");
}

// Content-Length is dropped when the upstream body was encoded (the runtime decodes it).
{
  const { res } = await release(`/${SHA}/${SUMMARY}`, {
    upstream: () => new Response("PAR1", { headers: { "Content-Encoding": "gzip", "Content-Length": "31" } }),
  });
  assert.equal(res.headers.get("Content-Length"), null);
  assert.equal(res.headers.get("Content-Encoding"), null);
}

// /ref: the commit at master from the API (the only REST call), cached for five minutes.
{
  const { res, calls } = await release("/ref", {
    e: { TENTATIVES_DATA_TOKEN: "t0ken" },
    upstream: () => new Response(`${SHA}\n`, { status: 200 }),
  });
  assert.equal(calls[0].url, "https://api.github.com/repos/aimesy/tentatives-data/commits/master");
  assert.equal(calls[0].init.headers.Accept, "application/vnd.github.sha");
  assert.equal(calls[0].init.headers.Authorization, "Bearer t0ken");
  assert.equal(res.status, 200);
  assert.equal(await res.text(), SHA);
  assert.equal(res.headers.get("Cache-Control"), "public, max-age=300");

  const denied = await release("/ref", { upstream: () => new Response('{"message":"Not Found"}', { status: 404 }) });
  assert.equal(denied.res.status, 502);
  assert.equal(denied.res.headers.get("Cache-Control"), "no-store");

  const viaGateway = await gateway("/ref?x=1", { headers: { Origin: SITE } });
  assert.equal(viaGateway.sent[0].url, `${BASE}/ref`);
}

// Only /ref calls the REST API; files come from raw.githubusercontent.com.
{
  for (const p of [`/${SHA}/${SUMMARY}`, `/${SHA}/${PDF}`, "/master/LIVE.md"]) {
    const { calls } = await release(p);
    assert.equal(calls.length, 1);
    assert.ok(calls[0].url.startsWith("https://raw.githubusercontent.com/aimesy/tentatives-data/"), p);
  }
}

// The Release entrypoint refuses paths outside the allowlist on its own too.
{
  const { res, calls } = await release(`/${SHA}/.github/x.yml`);
  assert.equal(res.status, 404);
  assert.equal(calls.length, 0);
  const robots = await release("/robots.txt");
  assert.equal(robots.res.status, 404);
  assert.equal(robots.calls.length, 0);
}

// Configuration: hostname, allowed origin, uncached gateway, cached Release, no token in the file.
{
  const toml = readFileSync(new URL("./data/wrangler.toml", import.meta.url), "utf8");
  assert.match(toml, /^name = "tentatives-data"$/m);
  assert.match(toml, /pattern = "tentatives-data\.amyc\.us", custom_domain = true/);
  assert.match(toml, /^ALLOWED_ORIGINS = "https:\/\/tentatives\.amyc\.us https:\/\/amyc\.us"$/m);
  assert.match(toml, /\[exports\.default\.cache\]\s+enabled = false/);
  assert.match(toml, /\[exports\.Release\.cache\]\s+enabled = true/);
  assert.match(toml, /period = 60/);
  assert.doesNotMatch(toml, /TENTATIVES_DATA_TOKEN\s*=/);
  const site = readFileSync(new URL("./site/wrangler.toml", import.meta.url), "utf8");
  assert.match(site, /^name = "tentatives"$/m);
  assert.match(site, /pattern = "tentatives\.amyc\.us", custom_domain = true/);
  assert.match(site, /directory = "\.\/dist"/);
  assert.doesNotMatch(site, /^main\s*=|^\[cache\]/m, "the viewer stays an uncached assets-only Worker, whose requests are free");
}

// Text and PDF are the same metered ruling. Source tables and packed shards
// cannot bypass the allowance at master or any retained commit.
{
  assert.equal(documentKey(route(`/master/${PDF}`)), `ruling:el-dorado/${ID}`);
  assert.equal(documentKey(route(`/${SHA}/${PDF}`)), `ruling:el-dorado/${ID}`, "one document whatever the ref");
  assert.equal(documentKey(route(`/master/${TEXT}`)), documentKey(route(`/${SHA}/${PDF}`)));
  for (const index of [`/master/${SUMMARY}`, "/master/LIVE.md", "/ref"]) assert.equal(documentKey(route(index)), null, `${index} is an index file`);
  assert.deepEqual(OPEN_PATHS, ["/master/LIVE.md"]);
  for (const ref of ["master", SHA]) {
    for (const path of ["data/el-dorado/rulings.parquet", "data/el-dorado/ruling-text/3f.json", "data/el-dorado/_viewer.json"]) {
      const refused = await gateway(`/${ref}/${path}`, { headers: { Origin: SITE, Range: "bytes=0-9" } });
      assert.equal(refused.res.status, 404);
      assert.equal(refused.sent.length, 0);
      const inner = await release(`/${ref}/${path}`);
      assert.equal(inner.res.status, 404);
      assert.equal(inner.calls.length, 0);
    }
  }
}

// Each metered content route maps to one prepared JSON record. It never
// reads an entire county source table or a packed collection of records.
{
  const prepared = { ruling_id: ID, county: "el-dorado", full_text: "complete chosen text", body_text: "chosen body", outcome_text: "chosen disposition" };
  const text = await release(`/${SHA}/${TEXT}`, { upstream: () => Response.json(prepared) });
  assert.equal(text.calls[0].url, `https://raw.githubusercontent.com/aimesy/tentatives-data/${SHA}/data/el-dorado/ruling-text/3f/${ID}.json`);
  assert.deepEqual(await text.res.json(), prepared);
  assert.equal(text.res.headers.get("Content-Type"), "application/json; charset=utf-8");
  const missing = await release(`/master/${TEXT}`, { upstream: () => new Response("missing", { status: 404 }) });
  assert.equal(missing.res.status, 404);
}

// The browser check and the document limits (worker/data/gate.js), through this gateway.
await checkGate({
  handle: (path, { method = "GET", headers = {}, body, env: e, counters, fetchImpl, now, log = () => {} }) =>
    handleGateway(new Request(`${BASE}${path}`, { method, headers, body }), e, {
      release: async () => new Response("%PDF", { headers: { "Content-Type": "application/pdf" } }),
      counters, fetchImpl, now, log,
    }),
  env: (extra = {}) => env({ SESSION_KEY: "test-session-key", TURNSTILE_SECRET_KEY: "test-turnstile-secret", ...extra }),
  site: SITE,
  document: (i) => `/master/data/el-dorado/rulings/3f${i.toString(16).padStart(30, "0")}.json`,
  slices: false,
  index: `/master/${SUMMARY}`,
  open: "/master/LIVE.md",
  cookiePrefix: "tentatives",
  sessionHeader: "X-Tentatives-Session",
});

console.log("worker tests passed");
