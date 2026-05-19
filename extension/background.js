// Background service worker. Receives upload requests from the popup,
// fetches PDFs (with host_permissions, no CORS issue), hashes them, checks
// GitHub for existence, uploads new ones via the Contents API, and appends
// a row to captures.ndjson.

import { sha256Hex, bufferToBase64 } from "./lib/hash.js";
import {
  fileExists,
  getFile,
  putFile,
  appendNdjsonLine,
} from "./lib/github.js";

// Per-county bulk-scan config. The root URL is fetched once at the start of a
// scan; pathTest is applied to each href on the page to decide whether it's a
// dept/calendar landing page worth walking.
const COUNTY_SCAN = {
  "el-dorado": {
    root: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings",
    pathTest: (path) =>
      /^\/online-services\/tentative-rulings\/tentative-rulings-dept-\d+\/?$/i.test(path),
  },
  "placer": {
    root: "https://www.placer.courts.ca.gov/online-services/tentative-rulings",
    // Any subpage of /online-services/tentative-rulings/<slug> — covers
    // tentative-rulings-law-and-motion, civil-osc-calendar, etc. The trailing
    // anchor keeps deeper paths out.
    pathTest: (path) =>
      /^\/online-services\/tentative-rulings\/[a-z][a-z0-9-]*\/?$/i.test(path)
      && path.replace(/\/$/, "") !== "/online-services/tentative-rulings",
  },
  "contra-costa": {
    // The CCC public landing page is just an iframe shell. The interesting
    // page is the iframe target on cc-courts.org: current rulings live at
    // motions-hearings-tentative.aspx, and historical at the archive page.
    // Walking both gives us everything that's currently linkable.
    root: "https://contracosta.courts.ca.gov/online-services/tentative-rulings",
    landings: [
      "https://contracosta.courts.ca.gov/online-services/tentative-rulings",
      "https://contracosta.courts.ca.gov/tentative-rulings-archive",
      "https://www.cc-courts.org/civil/motions-hearings-tentative.aspx",
      "https://www.cc-courts.org/civil/motions-hearings-tentative-archive.aspx",
    ],
    pathTest: () => true, // landings supplied explicitly
  },
};

const DEFAULT_PAGE_LOAD_DELAY_MS = 5000;

async function getConfig() {
  const {
    githubToken = "",
    githubOwner = "",
    githubRepo = "",
    githubBranch = "",
    pageLoadDelayMs = DEFAULT_PAGE_LOAD_DELAY_MS,
  } = await chrome.storage.local.get([
    "githubToken",
    "githubOwner",
    "githubRepo",
    "githubBranch",
    "pageLoadDelayMs",
  ]);
  return { githubToken, githubOwner, githubRepo, githubBranch, pageLoadDelayMs };
}

async function uploadOnePdf({ url, filename, county }, config) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  if (!githubToken || !githubOwner || !githubRepo) {
    throw new Error(
      "Extension not configured. Open the options page and set GitHub PAT / owner / repo.",
    );
  }

  // 1. Fetch PDF.
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`fetch ${url}: HTTP ${resp.status}`);
  const buffer = await resp.arrayBuffer();
  const sha = await sha256Hex(buffer);
  const archivePath = `archive/${county}/${sha.slice(0, 2)}/${sha}.pdf`;

  // 2. Idempotency: only upload the PDF if it isn't already in the archive.
  // We always log a capture event though — re-visits are meaningful provenance.
  const exists = await fileExists({
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch,
    path: archivePath,
    token: githubToken,
  });

  if (!exists) {
    const contentB64 = bufferToBase64(buffer);
    await putFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: archivePath,
      message: `${county}: capture ${filename} (sha=${sha.slice(0, 8)})`,
      contentBase64: contentB64,
      token: githubToken,
    });
  }

  // 3. Append a capture event to captures.ndjson (always — even when PDF was
  // already archived, the new visit is provenance worth keeping).
  const capture = {
    source_sha256: sha,
    source_url: url,
    discovered_filename: filename,
    fetched_at: new Date().toISOString(),
    wayback_ts: null,
    content_length: buffer.byteLength,
  };
  await appendNdjsonLine({
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch,
    path: `archive/${county}/captures.ndjson`,
    newLine: JSON.stringify(capture),
    message: `${county}: log capture ${filename}`,
    token: githubToken,
  });

  return {
    status: exists ? "skipped-exists" : "uploaded",
    sha,
    archivePath,
    size: buffer.byteLength,
  };
}

async function loadKnownUrls(county, config) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  if (!githubToken || !githubOwner || !githubRepo) return new Set();
  try {
    const f = await getFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: `archive/${county}/captures.ndjson`,
      token: githubToken,
    });
    const content = atob(f.content.replace(/\n/g, ""));
    const urls = new Set();
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const row = JSON.parse(trimmed);
        if (row.source_url) urls.add(row.source_url);
      } catch { /* skip malformed line */ }
    }
    return urls;
  } catch (e) {
    if (e.status === 404) return new Set();
    console.warn("[tentatives bg] could not load captures.ndjson:", e.message);
    return new Set();
  }
}

// Small inter-commit delay smooths over GitHub's eventual consistency on the
// Contents API; the 409 retry handles the cases where it isn't enough.
const COMMIT_THROTTLE_MS = 250;

async function uploadBatchStreaming({ pdfs, county, port }) {
  const config = await getConfig();
  const knownUrls = await loadKnownUrls(county, config);
  console.log(`[tentatives bg] ${knownUrls.size} URLs already in manifest`);

  for (const pdf of pdfs) {
    let result;
    if (knownUrls.has(pdf.url)) {
      result = { ...pdf, status: "already-captured" };
    } else {
      try {
        const r = await uploadOnePdf({ ...pdf, county }, config);
        result = { ...pdf, ...r };
        knownUrls.add(pdf.url);
        // Throttle between commits to ease the eventual-consistency window.
        if (r.status === "uploaded") {
          await new Promise((res) => setTimeout(res, COMMIT_THROTTLE_MS));
        }
      } catch (e) {
        console.error("[tentatives bg] upload error for", pdf.filename, e);
        result = { ...pdf, status: "error", error: String(e.message || e) };
      }
    }
    try {
      port.postMessage({ type: "result", result });
    } catch {
      // Popup closed mid-upload — keep going but stop streaming.
      console.warn("[tentatives bg] popup disconnected; finishing silently");
      return;
    }
  }
  try {
    port.postMessage({ type: "done" });
  } catch { /* popup closed */ }
}

// =========================================================== BULK SCAN
//
// Walks every dept/calendar landing page for a county in sequence: opens a
// background tab, navigates to each landing URL, waits for the page to settle
// (status=complete + configurable extra delay so the content script's
// document_idle harvest has run), reads window.__tentatives_pdfs, and feeds
// the PDFs through the same upload pipeline as single-page captures. URL
// dedup via captures.ndjson means re-running is cheap.

function landingTitle(url) {
  try {
    const path = new URL(url).pathname;
    const slug = path.split("/").filter(Boolean).pop() || path;
    return slug
      .replace(/^tentative-rulings-/, "")
      .replace(/-/g, " ");
  } catch {
    return url;
  }
}

async function discoverLandingPages(county) {
  const cfg = COUNTY_SCAN[county];
  if (!cfg) throw new Error(`bulk scan not configured for county "${county}"`);
  // Counties whose landing pages can't be reached by a static href crawl
  // (e.g. iframe-based portals) ship an explicit list instead.
  if (Array.isArray(cfg.landings) && cfg.landings.length) {
    return [...cfg.landings];
  }
  const r = await fetch(cfg.root, { credentials: "omit" });
  if (!r.ok) throw new Error(`fetch ${cfg.root}: HTTP ${r.status}`);
  const html = await r.text();
  const seen = new Set();
  const urls = [];
  for (const m of html.matchAll(/href=["']([^"']+)["']/gi)) {
    let u;
    try {
      u = new URL(m[1], cfg.root);
    } catch {
      continue;
    }
    if (!cfg.pathTest(u.pathname)) continue;
    // Normalize: strip query/hash and any trailing slash so equivalent links
    // collapse to a single entry.
    const canonical = `${u.origin}${u.pathname.replace(/\/$/, "")}`;
    if (seen.has(canonical)) continue;
    seen.add(canonical);
    urls.push(canonical);
  }
  urls.sort();
  return urls;
}

// Polls chrome.tabs.get for status="complete". Avoids the listener race after
// chrome.tabs.create (where "complete" can fire before onUpdated is attached)
// and keeps the MV3 service worker alive via continuous chrome API calls.
async function waitForTabComplete(tabId, { timeoutMs = 60000, pollMs = 200 } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    let tab;
    try {
      tab = await chrome.tabs.get(tabId);
    } catch {
      throw new Error("scan tab closed");
    }
    if (tab.status === "complete") return;
    await new Promise((r) => setTimeout(r, pollMs));
  }
  throw new Error(`tab load timed out after ${timeoutMs}ms`);
}

async function harvestFromTab(tabId) {
  // allFrames: true so cross-origin iframes (e.g. Contra Costa's cc-courts.org
  // iframe inside contracosta.courts.ca.gov) contribute their PDFs too.
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => window.__tentatives_pdfs || [],
  });
  const seen = new Set();
  const pdfs = [];
  for (const res of results || []) {
    for (const pdf of res?.result || []) {
      if (!pdf || !pdf.url || seen.has(pdf.url)) continue;
      seen.add(pdf.url);
      pdfs.push(pdf);
    }
  }
  return pdfs;
}

// Set by the popup via a "stop" message. Checked between pages and between
// PDFs so cancel is responsive without aborting an in-flight commit.
let bulkScanCancel = false;

async function scanAllStreaming({ county, port }) {
  bulkScanCancel = false;
  const config = await getConfig();
  if (!config.githubToken || !config.githubOwner || !config.githubRepo) {
    throw new Error(
      "Extension not configured. Open the options page and set GitHub PAT / owner / repo.",
    );
  }

  const delayMs = Number.isFinite(+config.pageLoadDelayMs)
    ? Math.max(0, +config.pageLoadDelayMs)
    : DEFAULT_PAGE_LOAD_DELAY_MS;

  port.postMessage({ type: "phase", phase: "discovering" });
  const landingUrls = await discoverLandingPages(county);
  port.postMessage({ type: "landings", urls: landingUrls });
  if (landingUrls.length === 0) {
    port.postMessage({ type: "done", reason: "no-landings" });
    return;
  }

  const knownUrls = await loadKnownUrls(county, config);
  console.log(`[tentatives bg] bulk scan: ${landingUrls.length} pages, ${knownUrls.size} URLs already in manifest`);

  let scanTab;
  try {
    scanTab = await chrome.tabs.create({ url: landingUrls[0], active: false });
  } catch (e) {
    throw new Error(`could not open scan tab: ${e.message || e}`);
  }
  const tabId = scanTab.id;

  try {
    for (let i = 0; i < landingUrls.length; i++) {
      if (bulkScanCancel) break;
      const url = landingUrls[i];
      const title = landingTitle(url);
      port.postMessage({
        type: "page-start",
        index: i,
        total: landingUrls.length,
        url,
        title,
      });

      try {
        // Skip the navigation for the first page since chrome.tabs.create
        // already pointed there; just wait for it to finish loading. For
        // subsequent pages, give Chrome a moment to flip status from
        // "complete" (previous page) to "loading" — otherwise the poll
        // below could see stale "complete" and return prematurely.
        if (i > 0) {
          await chrome.tabs.update(tabId, { url });
          await new Promise((r) => setTimeout(r, 300));
        }
        await waitForTabComplete(tabId);
        if (delayMs > 0) await new Promise((r) => setTimeout(r, delayMs));
        if (bulkScanCancel) break;

        const pdfs = await harvestFromTab(tabId);
        pdfs.sort((a, b) => (a.filename || a.url).localeCompare(b.filename || b.url));
        port.postMessage({
          type: "page-harvested",
          index: i,
          url,
          title,
          pdfCount: pdfs.length,
        });

        for (const pdf of pdfs) {
          if (bulkScanCancel) break;
          let result;
          if (knownUrls.has(pdf.url)) {
            result = { ...pdf, status: "already-captured" };
          } else {
            try {
              const r = await uploadOnePdf({ ...pdf, county }, config);
              result = { ...pdf, ...r };
              knownUrls.add(pdf.url);
              if (r.status === "uploaded") {
                await new Promise((res) => setTimeout(res, COMMIT_THROTTLE_MS));
              }
            } catch (e) {
              console.error("[tentatives bg] bulk upload error for", pdf.filename, e);
              result = { ...pdf, status: "error", error: String(e.message || e) };
            }
          }
          try {
            port.postMessage({ type: "result", result, pageIndex: i, pageTitle: title });
          } catch {
            console.warn("[tentatives bg] popup disconnected; finishing silently");
            // Keep going even if popup closed — the bulk scan is long-running
            // and the user may have closed the popup intentionally.
          }
        }
      } catch (e) {
        console.error(`[tentatives bg] bulk scan page ${url} failed:`, e);
        try {
          port.postMessage({
            type: "page-error",
            index: i,
            url,
            title,
            error: String(e.message || e),
          });
        } catch { /* port closed */ }
      }
    }
  } finally {
    try { await chrome.tabs.remove(tabId); } catch { /* already gone */ }
  }

  try {
    port.postMessage({ type: "done", reason: bulkScanCancel ? "stopped" : "completed" });
  } catch { /* port closed */ }
  bulkScanCancel = false;
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "upload") {
    port.onMessage.addListener(async (msg) => {
      if (msg.type !== "start") return;
      try {
        await uploadBatchStreaming({ pdfs: msg.pdfs, county: msg.county, port });
      } catch (e) {
        console.error("[tentatives bg] fatal", e);
        try {
          port.postMessage({ type: "error", error: String(e.message || e) });
        } catch { /* port closed */ }
      }
    });
    return;
  }
  if (port.name === "bulk-scan") {
    port.onMessage.addListener(async (msg) => {
      if (msg.type === "stop") {
        bulkScanCancel = true;
        return;
      }
      if (msg.type !== "start") return;
      try {
        await scanAllStreaming({ county: msg.county, port });
      } catch (e) {
        console.error("[tentatives bg] bulk scan fatal", e);
        try {
          port.postMessage({ type: "error", error: String(e.message || e) });
        } catch { /* port closed */ }
      }
    });
    return;
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  console.log("[tentatives bg] message", msg?.type);
  if (msg && msg.type === "page-loaded") {
    const text = msg.pdfs.length ? String(msg.pdfs.length) : "";
    chrome.action.setBadgeText({ text });
    chrome.action.setBadgeBackgroundColor({ color: msg.pdfs.length ? "#3b82f6" : "#9ca3af" });
  }
});

chrome.runtime.onInstalled.addListener((details) => {
  console.log("[tentatives bg] installed", details.reason);
});
