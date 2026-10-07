// Logic for the tentatives-data Worker, kept free of imports only Workers
// have, so worker/worker.test.mjs can run it under Node. index.js wires it up.
// Adapted from aimesy/mfa's worker/release.js; gate.js (the same file in
// every data Worker) holds the browser check and the document limits.
//
// The data repository (aimesy/tentatives-data) is private. The viewer at
// https://tentatives.amyc.us/ reads it through this Worker at
// https://tentatives-data.amyc.us/, whose URLs mirror raw.githubusercontent.com:
//   /<ref>/data/<county>/summary.json              metadata, disposition and opening lines
//   /<ref>/data/<county>/rulings/<id>.json         one metered ruling's complete text
//   /<ref>/archive/<county>/rulings/<xx>/<id>.pdf  the PDF slice of one ruling
//   /<ref>/LIVE.md                                 the metrics table on amyc.us
//   /ref                                           the commit at master
//   /session                                       POST a Turnstile token; answers with a session cookie
//
// GitHub's REST API allows 5,000 requests an hour, shared by every token Amy
// owns, so files come from raw.githubusercontent.com and only /ref uses the
// API; Workers Caching keeps /ref for five minutes and each file at a commit
// for a year.
//
// Two entrypoints:
//   gateway (default export, never cached): CORS preflight, the origin check,
//     the flood guard for each address, the session check and the document
//     limits (gate.js), then a clean request to the Release entrypoint.
//   release (the Release entrypoint, cached by Workers Caching): fetches the
//     file from GitHub with the read-only token and returns it with fresh headers.
// The cache sits in front of each entrypoint, so the gateway must stay
// uncached or a cache hit would skip the origin check and the rate limit.
// Workers Caching strips Range before it calls Release, stores the full file
// and answers each range from the stored copy.

import { addressKey, chargeDocument, checkSessionAccess, hasSession, readSession, startSession } from "./gate.js";

export const REPO = "aimesy/tentatives-data";
export const BRANCH = "master";
// Copied from site/app.js; site/check-static.mjs fails if the two differ.
export const DATA_PATH = /^(?:data\/[a-z0-9-]+\/(?:summary\.json|rulings\/[0-9a-f]{32}\.json)|archive\/[a-z0-9-]+\/rulings\/([0-9a-f]{2})\/\1[0-9a-f]{30}\.pdf)$/;
// The metrics table the amyc.us home page shows (aimesy/me assets/projects.js).
export const HOME_PATH = /^LIVE\.md$/;
const SHA = /^[0-9a-f]{40}$/;
const USER_AGENT = "tentatives-data-worker (+https://tentatives.amyc.us/)";
const RETRY_AFTER_SECONDS = "60"; // the period of the RATE_LIMITER binding in wrangler.toml

const IMMUTABLE = "public, max-age=31536000, immutable";
// /ref and files at master: at most one GitHub call per five minutes each.
const SHORT = "public, max-age=300";
const API_VERSION = "2022-11-28";
const NO_STORE = "no-store";

const CONTENT_TYPES = {
  pdf: "application/pdf",
  parquet: "application/octet-stream",
  md: "text/plain; charset=utf-8",
  json: "application/json; charset=utf-8",
};

const ROBOTS = "User-agent: *\nDisallow: /\n";

// What gate.js needs from this Worker. REQUIRE_SESSION "true" refuses data
// requests without a session from the Turnstile check; otherwise the state
// is only reported in X-Tentatives-Session.
export const GATE = {
  cookiePrefix: "tentatives",
  sessionHeader: "X-Tentatives-Session",
  viewer: "https://tentatives.amyc.us",
};

// Open summary files: exact paths that skip the session check (they still
// need an allowed Origin and pass the flood guard). The amyc.us home page
// (aimesy/me assets/projects.js LIVE_REPOS) reads LIVE.md at master.
export const OPEN_PATHS = ["/master/LIVE.md"];

// A ruling's text and PDF share one document allowance, whatever the ref.
// Only metadata summaries, LIVE.md and /ref are exempt. Source tables and
// internal record files are not routable, even at an old commit.
export function documentKey(target) {
  if (target?.kind !== "file") return null;
  const text = /^data\/([a-z0-9-]+)\/rulings\/([0-9a-f]{32})\.json$/.exec(target.path);
  const pdf = /^archive\/([a-z0-9-]+)\/rulings\/[0-9a-f]{2}\/([0-9a-f]{32})\.pdf$/.exec(target.path);
  const match = text || pdf;
  return match ? `ruling:${match[1]}/${match[2]}` : null;
}

// Which file a path names: { kind: "robots" | "ref" | "file", ref, path },
// or null for anything the viewer would never ask for.
export function route(pathname) {
  if (pathname === "/robots.txt") return { kind: "robots" };
  if (pathname === "/ref") return { kind: "ref" };
  if (pathname === "/session") return { kind: "session" };
  const m = /^\/([^/]+)\/(.+)$/.exec(pathname);
  if (!m) return null;
  const [, ref, path] = m;
  if (!(SHA.test(ref) || ref === BRANCH)) return null;
  if (!(DATA_PATH.test(path) || HOME_PATH.test(path)) || path.includes("..")) return null;
  return { kind: "file", ref, path };
}

export function allowedOrigins(env) {
  return String(env?.ALLOWED_ORIGINS || "").split(/[\s,]+/).filter(Boolean);
}

// The calling page's origin: Origin when the browser sent one (every fetch()),
// else the origin of Referer (a PDF slice opened in a new tab). Null unless listed.
export function callerOrigin(request, origins) {
  const origin = request.headers.get("Origin");
  if (origin !== null) return origins.includes(origin) ? origin : null;
  const referer = request.headers.get("Referer");
  if (!referer) return null;
  try {
    const o = new URL(referer).origin;
    return origins.includes(o) ? o : null;
  } catch {
    return null;
  }
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Retry-After, X-Check, X-Limit, X-Tentatives-Session, X-Trusted-Key",
  };
}

function addVary(headers, name) {
  const vary = headers.get("Vary");
  if (!vary) headers.set("Vary", name);
  else if (!vary.split(",").some((v) => v.trim().toLowerCase() === name.toLowerCase())) headers.set("Vary", `${vary}, ${name}`);
}

function plain(status, text, headers = {}) {
  return new Response(text, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": NO_STORE,
      "X-Content-Type-Options": "nosniff",
      "X-Robots-Tag": "noindex",
      ...headers,
    },
  });
}

// Default export. `release(request)` calls the cached Release entrypoint
// (ctx.exports.Release.fetch in index.js; a stub in the tests); a bare
// function is taken as `release`. `counters` answers the DailyQuota objects
// for a browser and an address (gate.js durableCounters in index.js;
// memoryCounters in the tests). `log` gets one line for each data request
// (Workers Logs): its kind, session state and limit outcome, never an address.
export async function handleGateway(request, env, deps = {}) {
  const { release, counters, fetchImpl = fetch, now = Date.now(), log = (line) => console.log(line) } = typeof deps === "function" ? { release: deps } : deps;
  const url = new URL(request.url);
  const method = request.method;

  if (url.pathname === "/robots.txt" && (method === "GET" || method === "HEAD")) {
    return new Response(method === "HEAD" ? null : ROBOTS, {
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=86400", "X-Robots-Tag": "noindex" },
    });
  }

  const origins = allowedOrigins(env);
  const origin = callerOrigin(request, origins);

  if (method === "OPTIONS") {
    if (!origin) return plain(403, "Forbidden\n");
    return new Response(null, {
      status: 204,
      headers: {
        ...corsHeaders(origin),
        "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Range",
        "Access-Control-Max-Age": "86400",
        "Vary": "Origin",
        "X-Robots-Tag": "noindex",
      },
    });
  }

  if (!origin) return plain(403, "Forbidden\n");
  const target = route(url.pathname);
  const methods = target?.kind === "session" ? ["POST"] : ["GET", "HEAD"];
  if (!methods.includes(method)) {
    return plain(405, "Method not allowed\n", { ...corsHeaders(origin), Allow: [...methods, "OPTIONS"].join(", "), Vary: "Origin" });
  }

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const address = addressKey(ip);
  if (env.RATE_LIMITER) {
    const { success } = await env.RATE_LIMITER.limit({ key: address });
    if (!success) {
      return plain(429, "Too many requests. Retry in 60 seconds.\n", {
        ...corsHeaders(origin),
        "Retry-After": RETRY_AFTER_SECONDS,
        Vary: "Origin",
      });
    }
  }

  if (!target || target.kind === "robots") return plain(404, "Not found\n", { ...corsHeaders(origin), Vary: "Origin" });

  // The browser check and the document limits (gate.js).
  const cors = { ...corsHeaders(origin), Vary: "Origin" };
  const cfg = { ...GATE, origins };
  const record = (fields) => log(JSON.stringify(fields));
  if (target.kind === "session") {
    return startSession(request, env, { ip, address, cors, cfg, counters, fetchImpl, now, log: record });
  }
  const open = OPEN_PATHS.includes(url.pathname);
  const docKey = open ? null : documentKey(target);
  const session = await readSession(request, env, address, now, cfg);
  if (!open && !hasSession(session) && env.REQUIRE_SESSION === "true") {
    record({ kind: target.kind, document: Boolean(docKey), session: session.state, outcome: "no session" });
    return plain(401, `Open the viewer at ${GATE.viewer}; it checks your browser first.\n`, { ...cors, [GATE.sessionHeader]: session.state });
  }
  let outcome = open ? "open" : "index";
  const sessionRefusal = open ? null : await checkSessionAccess(env, { session, cors, cfg, counters, now });
  if (sessionRefusal) return sessionRefusal;
  if (docKey && counters) {
    const charged = await chargeDocument(env, { session, address, key: docKey, cors, cfg, counters, now });
    outcome = charged.outcome;
    if (charged.refusal) {
      record({ kind: target.kind, document: true, session: session.state, outcome });
      return charged.refusal;
    }
  }
  record({ kind: target.kind, document: Boolean(docKey), session: session.state, outcome });

  // A fresh request from the path alone: no query string (the cache key is
  // path plus query) and no headers but Range (Authorization or cookies would
  // make the cache bypass).
  const headers = {};
  const range = request.headers.get("Range");
  if (range) headers.Range = range;
  const res = await release(new Request(new URL(url.pathname, url.origin), { method, headers }));

  const out = new Response(res.body, res);
  for (const [k, v] of Object.entries(corsHeaders(origin))) out.headers.set(k, v);
  addVary(out.headers, "Origin");
  out.headers.set("X-Robots-Tag", "noindex");
  out.headers.set(GATE.sessionHeader, session.state);
  if (!open) out.headers.set("Cache-Control", "private, no-store");
  return out;
}

function upstreamHeaders(env, extra = {}) {
  const headers = { "User-Agent": USER_AGENT, ...extra };
  // Absent only in local development without worker/data/.dev.vars.
  if (env?.TENTATIVES_DATA_TOKEN) headers.Authorization = `Bearer ${env.TENTATIVES_DATA_TOKEN}`;
  return headers;
}

function contentType(path) {
  const ext = /\.([A-Za-z0-9]+)$/.exec(path)?.[1].toLowerCase();
  return CONTENT_TYPES[ext] || "application/octet-stream";
}

// Turns GitHub's answer for one file into the Worker's: fresh headers only.
function fileResponse(res, path, cacheControl, method) {
  if (res.status === 404 || res.status === 410) return plain(404, "Not found\n");
  if (res.status === 416) {
    const cr = res.headers.get("Content-Range");
    return plain(416, "Range not satisfiable\n", cr ? { "Content-Range": cr } : {});
  }
  if (res.status !== 200 && res.status !== 206) return plain(502, `GitHub answered ${res.status}\n`);

  const type = contentType(path);
  const headers = new Headers({
    "Content-Type": type,
    "Cache-Control": cacheControl,
    "Accept-Ranges": "bytes",
    "X-Content-Type-Options": "nosniff",
  });
  const etag = res.headers.get("ETag");
  if (etag) headers.set("ETag", etag);
  // The runtime decodes a gzip body, so the upstream length would be wrong.
  const length = res.headers.get("Content-Length");
  if (length && !res.headers.get("Content-Encoding")) headers.set("Content-Length", length);
  if (res.status === 206) {
    const cr = res.headers.get("Content-Range");
    if (cr) headers.set("Content-Range", cr);
  }
  if (type !== "application/pdf") headers.set("Content-Security-Policy", "default-src 'none'; sandbox");
  return new Response(method === "HEAD" ? null : res.body, { status: res.status, headers });
}

// Release entrypoint. Fetches one file, or the commit at master, from GitHub.
export async function handleRelease(request, env, fetchImpl = fetch) {
  const url = new URL(request.url);
  const target = route(url.pathname);
  if (target?.kind === "session") return plain(404, "Not found\n");
  if (!target || target.kind === "robots") return plain(404, "Not found\n");

  if (target.kind === "ref") {
    let res;
    try {
      res = await fetchImpl(`https://api.github.com/repos/${REPO}/commits/${BRANCH}`, {
        headers: upstreamHeaders(env, { Accept: "application/vnd.github.sha", "X-GitHub-Api-Version": API_VERSION }),
      });
    } catch {
      return plain(502, "GitHub did not answer\n");
    }
    const sha = res.ok ? (await res.text()).trim() : "";
    if (!SHA.test(sha)) return plain(502, `GitHub answered ${res.status} for ${BRANCH}\n`);
    return new Response(sha, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": SHORT,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
      },
    });
  }

  // Metadata indexes are prepared and verified before deployment by
  // ingest/build_viewer_data.py. Stream them without parsing large county
  // indexes within the Free Worker's CPU limit. One content route maps to
  // one complete JSON record, never a packed file of other rulings.
  const ruling = /^data\/([a-z0-9-]+)\/rulings\/([0-9a-f]{32})\.json$/.exec(target.path);
  const upstreamPath = ruling ? `data/${ruling[1]}/ruling-text/${ruling[2].slice(0, 2)}/${ruling[2]}.json` : target.path;

  const extra = {};
  const range = request.headers.get("Range");
  if (range) extra.Range = range;
  let res;
  try {
    res = await fetchImpl(`https://raw.githubusercontent.com/${REPO}/${target.ref}/${upstreamPath}`, {
      method: request.method === "HEAD" ? "HEAD" : "GET",
      headers: upstreamHeaders(env, extra),
    });
  } catch {
    return plain(502, "GitHub did not answer\n");
  }
  return fileResponse(res, target.path, SHA.test(target.ref) ? IMMUTABLE : SHORT, request.method);
}
