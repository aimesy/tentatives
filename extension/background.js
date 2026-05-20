// Background service worker. Receives upload requests from the sidebar,
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
import {
  COUNTY_SCAN,
  DEFAULT_GITHUB,
  VOLATILE_URL_COUNTIES,
} from "./lib/counties.js";

const DEFAULT_PAGE_LOAD_DELAY_MS = 5000;
const BULK_SCAN_MAX_PAGE_RETRIES = 3;
const BULK_SCAN_RETRY_DELAY_MS = 1000;

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

async function fetchAndHashPdf(pdf) {
  const fetchUrl = pdf.fetchUrl || pdf.fetch_url || pdf.url;
  const resp = await fetch(fetchUrl);
  if (!resp.ok) throw new Error(`fetch ${fetchUrl}: HTTP ${resp.status}`);
  const buffer = await resp.arrayBuffer();
  const sha = await sha256Hex(buffer);
  return {
    fetchUrl,
    buffer,
    sha,
    size: buffer.byteLength,
  };
}

async function uploadOnePdf(pdf, config, fetchedPdf = null) {
  const { url, filename, county } = pdf;
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  if (!githubToken || !githubOwner || !githubRepo) {
    throw new Error(
      "Extension not configured. Open the options page and set GitHub PAT / owner / repo.",
    );
  }

  // 1. Fetch PDF.
  const { fetchUrl, buffer, sha, size } = fetchedPdf || await fetchAndHashPdf(pdf);
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
    county,
    source_sha256: sha,
    source_url: url,
    source_fetch_url: fetchUrl === url ? null : fetchUrl,
    discovered_filename: filename,
    fetched_at: new Date().toISOString(),
    wayback_ts: pdf.waybackTs || pdf.wayback_ts || null,
    content_length: size,
    dept_hint: pdf.deptHint || pdf.dept_hint || null,
    division_hint: pdf.divisionHint || pdf.division_hint || null,
    date_hint: pdf.dateHint || pdf.date_hint || null,
    label_hint: pdf.labelHint || pdf.label_hint || null,
    page_title_hint: pdf.pageTitleHint || pdf.page_title_hint || null,
    source_page_url: pdf.sourcePageUrl || pdf.source_page_url || null,
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
    size,
  };
}

function emptyCaptureIndex() {
  return {
    urlKeys: new Set(),
    shaByUrlKey: new Map(),
  };
}

function rememberCapture(index, url, waybackTs = null, sha = null) {
  const key = captureKey(url, waybackTs);
  index.urlKeys.add(key);
  if (sha) {
    let shas = index.shaByUrlKey.get(key);
    if (!shas) {
      shas = new Set();
      index.shaByUrlKey.set(key, shas);
    }
    shas.add(sha);
  }
  return key;
}

async function loadCaptureIndex(county, config) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  if (!githubToken || !githubOwner || !githubRepo) return emptyCaptureIndex();
  try {
    const f = await getFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: `archive/${county}/captures.ndjson`,
      token: githubToken,
    });
    const content = atob(f.content.replace(/\n/g, ""));
    const index = emptyCaptureIndex();
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const row = JSON.parse(trimmed);
        if (row.source_url) {
          rememberCapture(index, row.source_url, row.wayback_ts, row.source_sha256);
        }
      } catch { /* skip malformed line */ }
    }
    return index;
  } catch (e) {
    if (e.status === 404) return emptyCaptureIndex();
    console.warn("[tentatives bg] could not load captures.ndjson:", e.message);
    return emptyCaptureIndex();
  }
}

function captureKey(url, waybackTs = null) {
  return `${url}::${waybackTs || ""}`;
}

async function uploadOrSkipPdf(pdf, county, config, captures) {
  const waybackTs = pdf.waybackTs || pdf.wayback_ts || null;
  const key = captureKey(pdf.url, waybackTs);

  if (!VOLATILE_URL_COUNTIES.has(county)) {
    if (captures.urlKeys.has(key)) {
      return { status: "already-captured" };
    }
    const result = await uploadOnePdf({ ...pdf, county }, config);
    rememberCapture(captures, pdf.url, waybackTs, result.sha);
    return result;
  }

  const fetched = await fetchAndHashPdf(pdf);
  if (captures.shaByUrlKey.get(key)?.has(fetched.sha)) {
    return {
      status: "already-captured",
      sha: fetched.sha,
      size: fetched.size,
      duplicateReason: "same-url-same-sha",
    };
  }

  const result = await uploadOnePdf({ ...pdf, county }, config, fetched);
  rememberCapture(captures, pdf.url, waybackTs, result.sha);
  return result;
}

function pageCaptureKey(url, sha) {
  return `${url || ""}::${sha || ""}`;
}

async function loadArtifactCaptureIndex(county, config, filename) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  const keys = new Set();
  if (!githubToken || !githubOwner || !githubRepo) return keys;
  try {
    const f = await getFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: `archive/${county}/${filename}`,
      token: githubToken,
    });
    const content = atob(f.content.replace(/\n/g, ""));
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        const row = JSON.parse(trimmed);
        const sha = row.source_sha256 || row.layout_sha256;
        if (row.source_url && sha) {
          keys.add(pageCaptureKey(row.source_url, sha));
        }
      } catch { /* skip malformed line */ }
    }
  } catch (e) {
    if (e.status !== 404) {
      console.warn(`[tentatives bg] could not load ${filename}:`, e.message);
    }
  }
  return keys;
}

async function loadPageCaptureIndex(county, config) {
  return loadArtifactCaptureIndex(county, config, "page-captures.ndjson");
}

async function loadLayoutCaptureIndex(county, config) {
  return loadArtifactCaptureIndex(county, config, "layout-captures.ndjson");
}

function textToBase64(text) {
  return bufferToBase64(new TextEncoder().encode(text).buffer);
}

async function uploadOrSkipPageSnapshot(snapshot, county, config, pageCaptures) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  const sourceUrl = snapshot.url || snapshot.source_url || "";
  const html = String(snapshot.html || "");
  if (!sourceUrl || !html.trim()) {
    return {
      status: "error",
      error: "empty page snapshot",
      filename: sourceUrl || "page snapshot",
    };
  }

  const bytes = new TextEncoder().encode(html);
  const sha = await sha256Hex(bytes.buffer);
  const key = pageCaptureKey(sourceUrl, sha);
  const title = snapshot.title || sourceUrl;
  const filename = `${title}.html`;
  if (pageCaptures.has(key)) {
    return {
      status: "page-unchanged",
      sha,
      size: bytes.byteLength,
      filename,
      url: sourceUrl,
    };
  }

  const archivePath = `archive/${county}/pages/${sha.slice(0, 2)}/${sha}.html`;
  const exists = await fileExists({
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch,
    path: archivePath,
    token: githubToken,
  });
  if (!exists) {
    await putFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: archivePath,
      message: `${county}: capture page ${sha.slice(0, 8)}`,
      contentBase64: textToBase64(html),
      token: githubToken,
    });
  }

  const capture = {
    county,
    source_sha256: sha,
    source_url: sourceUrl,
    title,
    page_kind: snapshot.pageKind || snapshot.page_kind || null,
    captured_at: new Date().toISOString(),
    content_length: bytes.byteLength,
    archive_path: archivePath,
  };
  await appendNdjsonLine({
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch,
    path: `archive/${county}/page-captures.ndjson`,
    newLine: JSON.stringify(capture),
    message: `${county}: log page capture ${sha.slice(0, 8)}`,
    token: githubToken,
  });
  pageCaptures.add(key);
  return {
    status: exists ? "page-logged" : "page-captured",
    sha,
    archivePath,
    size: bytes.byteLength,
    filename,
    url: sourceUrl,
  };
}

async function uploadOrSkipLayoutDoc(layoutDoc, county, config, layoutCaptures) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  const sourceUrl = layoutDoc.url || "";
  const json = String(layoutDoc.json || "");
  if (!sourceUrl || !json.trim()) {
    return {
      status: "error",
      error: "empty layout snapshot",
      filename: sourceUrl || "layout snapshot",
    };
  }

  const bytes = new TextEncoder().encode(json);
  const sha = await sha256Hex(bytes.buffer);
  const key = pageCaptureKey(sourceUrl, sha);
  const title = layoutDoc.title || sourceUrl;
  const filename = `${title} layout.json`;
  if (layoutCaptures.has(key)) {
    return {
      status: "layout-unchanged",
      sha,
      size: bytes.byteLength,
      filename,
      url: sourceUrl,
    };
  }

  const archivePath = `archive/${county}/layouts/${sha.slice(0, 2)}/${sha}.json`;
  const exists = await fileExists({
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch,
    path: archivePath,
    token: githubToken,
  });
  if (!exists) {
    await putFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: archivePath,
      message: `${county}: capture layout ${sha.slice(0, 8)}`,
      contentBase64: textToBase64(json),
      token: githubToken,
    });
  }

  const capture = {
    county,
    source_sha256: sha,
    source_url: sourceUrl,
    title,
    captured_at: new Date().toISOString(),
    content_length: bytes.byteLength,
    archive_path: archivePath,
    layout_version: layoutDoc.layoutVersion || 1,
  };
  await appendNdjsonLine({
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch,
    path: `archive/${county}/layout-captures.ndjson`,
    newLine: JSON.stringify(capture),
    message: `${county}: log layout capture ${sha.slice(0, 8)}`,
    token: githubToken,
  });
  layoutCaptures.add(key);
  return {
    status: exists ? "layout-logged" : "layout-captured",
    sha,
    archivePath,
    size: bytes.byteLength,
    filename,
    url: sourceUrl,
  };
}

// Small inter-commit delay smooths over GitHub's eventual consistency on the
// Contents API; the 409 retry handles the cases where it isn't enough.
const COMMIT_THROTTLE_MS = 250;

async function uploadBatchStreaming({ pdfs, county, port }) {
  const config = await getConfig();
  const captures = await loadCaptureIndex(county, config);
  console.log(`[tentatives bg] ${captures.urlKeys.size} URLs already in manifest`);

  for (const pdf of pdfs) {
    let result;
    try {
      const r = await uploadOrSkipPdf(pdf, county, config, captures);
      result = { ...pdf, ...r };
      // Throttle between commits to ease the eventual-consistency window.
      if (r.status === "uploaded") {
        await new Promise((res) => setTimeout(res, COMMIT_THROTTLE_MS));
      }
    } catch (e) {
      console.error("[tentatives bg] upload error for", pdf.filename, e);
      result = { ...pdf, status: "error", error: String(e.message || e) };
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
// the PDFs through the same upload pipeline as single-page captures. Most
// counties use URL dedup via captures.ndjson; counties with stable PDF URLs
// fetch/hash first so changed content is not missed.

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
async function waitForTabComplete(tabId, { timeoutMs = 60000, pollMs = 200, control = null } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (control && !(await bulkScanCheckpoint(control))) return false;
    let tab;
    try {
      tab = await chrome.tabs.get(tabId);
    } catch {
      throw new Error("scan tab closed");
    }
    if (tab.status === "complete") return true;
    if (control) {
      if (!(await controlledBulkScanDelay(pollMs, control))) return false;
    } else {
      await new Promise((r) => setTimeout(r, pollMs));
    }
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

async function harvestPageSnapshotsFromTab(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => window.__tentatives_pages || [],
  });
  const seen = new Set();
  const pages = [];
  for (const res of results || []) {
    for (const page of res?.result || []) {
      if (!page || !page.url || !page.html) continue;
      const key = `${page.url}::${page.pageKind || ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      pages.push(page);
    }
  }
  return pages;
}

async function harvestLayoutDocsFromTab(tabId) {
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => {
      const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const pattern = (value) => clean(value)
        .toLowerCase()
        .replace(/\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b/g, "{date}")
        .replace(/\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\b/g, "{date}")
        .replace(/\b\d{6,}\b/g, "{number}")
        .replace(/[a-f0-9]{16,}/g, "{hash}")
        .slice(0, 180);
      const pathPattern = (raw) => {
        try {
          const u = new URL(raw, location.href);
          const path = u.pathname
            .replace(/\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b/g, "{date}")
            .replace(/\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\b/g, "{date}")
            .replace(/\d{6,}/g, "{number}")
            .replace(/[a-f0-9]{16,}/gi, "{hash}");
          return `${u.hostname}${path}`.toLowerCase();
        } catch {
          return pattern(raw);
        }
      };
      const selectorOf = (el) => {
        const parts = [];
        let cur = el;
        while (cur && cur.nodeType === Node.ELEMENT_NODE && cur !== document.documentElement) {
          const tag = cur.tagName.toLowerCase();
          const id = cur.id ? `#${pattern(cur.id)}` : "";
          const cls = [...cur.classList].slice(0, 3).map((c) => `.${pattern(c)}`).join("");
          parts.unshift(`${tag}${id}${cls}`);
          cur = cur.parentElement;
          if (parts.length >= 4) break;
        }
        return parts.join(" > ");
      };
      const count = (sel) => document.querySelectorAll(sel).length;
      const uniqueSorted = (items, limit = 120) => [...new Set(items.filter(Boolean))].sort().slice(0, limit);

      const links = uniqueSorted([...document.querySelectorAll("a[href]")].map((a) => JSON.stringify({
        near: selectorOf(a.parentElement || a),
        text: pattern(a.textContent),
        href: pathPattern(a.getAttribute("href")),
      }))).map((s) => JSON.parse(s));
      const iframes = uniqueSorted([...document.querySelectorAll("iframe[src]")].map((el) =>
        pathPattern(el.getAttribute("src"))
      ));
      const forms = uniqueSorted([...document.querySelectorAll("form")].map((form) => JSON.stringify({
        near: selectorOf(form),
        method: pattern(form.getAttribute("method") || "get"),
        action: pathPattern(form.getAttribute("action") || location.href),
        controls: uniqueSorted([...form.querySelectorAll("input, select, textarea, button")].map((el) =>
          `${el.tagName.toLowerCase()}:${pattern(el.getAttribute("type") || "")}:${pattern(el.getAttribute("name") || el.id || "")}`
        ), 40),
      }))).map((s) => JSON.parse(s));
      const tables = uniqueSorted([...document.querySelectorAll("table")].map((table) => JSON.stringify({
        near: selectorOf(table),
        headers: [...table.querySelectorAll("th")].slice(0, 20).map((th) => pattern(th.textContent)),
      }))).map((s) => JSON.parse(s));
      const accordions = uniqueSorted([...document.querySelectorAll("details, [aria-expanded], .accordion, .usa-accordion, .collapsible")].map((el) =>
        `${selectorOf(el)}:${pattern(el.getAttribute("aria-controls") || el.getAttribute("aria-expanded") || "")}`
      ));

      const layout = {
        layout_version: 1,
        source_url: location.href,
        title: pattern(document.title),
        body_classes: uniqueSorted([...(document.body?.classList || [])].map(pattern), 30),
        counts: {
          has_links: count("a[href]") > 0,
          has_pdf_links: [...document.querySelectorAll("a[href]")].some((a) => /\.pdf(?:$|[?#])/i.test(a.href)),
          iframes: count("iframe[src]"),
          forms: count("form"),
          selects: count("select"),
          tables: count("table"),
          details: count("details"),
          aria_expanded: count("[aria-expanded]"),
        },
        iframes,
        links,
        forms,
        tables,
        accordions,
      };
      return {
        url: location.href,
        title: clean(document.title) || location.href,
        layoutVersion: 1,
        json: JSON.stringify(layout, null, 2) + "\n",
      };
    },
  });
  const seen = new Set();
  const layouts = [];
  for (const res of results || []) {
    const layout = res?.result;
    if (!layout?.url || !layout?.json || seen.has(layout.url)) continue;
    seen.add(layout.url);
    layouts.push(layout);
  }
  return layouts;
}

// Set by the side panel via pause/resume/stop messages. Checked between pages,
// during page waits, and between PDFs so control is responsive without aborting
// an in-flight commit.
let bulkScanControl = null;

function createBulkScanControl(port) {
  return {
    cancel: false,
    paused: false,
    port,
    resumeWaiters: new Set(),
  };
}

function postBulkScanMessage(port, msg) {
  try {
    port.postMessage(msg);
    return true;
  } catch {
    return false;
  }
}

function wakeBulkScanWaiters(control) {
  for (const resolve of control.resumeWaiters) resolve();
  control.resumeWaiters.clear();
}

function setBulkScanPaused(control, paused) {
  if (!control || control.cancel) return;
  control.paused = paused;
  if (!paused) wakeBulkScanWaiters(control);
  postBulkScanMessage(control.port, { type: "control-state", paused });
}

function stopBulkScan(control) {
  if (!control) return;
  control.cancel = true;
  control.paused = false;
  wakeBulkScanWaiters(control);
  postBulkScanMessage(control.port, { type: "control-state", paused: false, stopped: true });
}

async function waitForBulkScanResume(control) {
  while (control.paused && !control.cancel) {
    await new Promise((resolve) => {
      control.resumeWaiters.add(resolve);
    });
  }
}

async function bulkScanCheckpoint(control) {
  if (control.cancel) return false;
  if (control.paused) await waitForBulkScanResume(control);
  return !control.cancel;
}

async function controlledBulkScanDelay(ms, control, stepMs = 200) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (!(await bulkScanCheckpoint(control))) return false;
    const waitMs = Math.min(stepMs, deadline - Date.now());
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }
  return bulkScanCheckpoint(control);
}

async function scanAllStreaming({ county, port, explicitUrls = null }) {
  const control = createBulkScanControl(port);
  bulkScanControl = control;
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
  // Caller can pass an explicit list (sidebar "Fetch" on a single landing
  // page) to skip the index-page crawl entirely.
  const landingUrls = explicitUrls && explicitUrls.length
    ? [...explicitUrls]
    : await discoverLandingPages(county);
  if (!(await bulkScanCheckpoint(control))) {
    port.postMessage({ type: "done", reason: "stopped" });
    if (bulkScanControl === control) bulkScanControl = null;
    return;
  }
  port.postMessage({ type: "landings", urls: landingUrls });
  if (landingUrls.length === 0) {
    port.postMessage({ type: "done", reason: "no-landings" });
    if (bulkScanControl === control) bulkScanControl = null;
    return;
  }

  const captures = await loadCaptureIndex(county, config);
  const pageCaptures = await loadPageCaptureIndex(county, config);
  const layoutCaptures = await loadLayoutCaptureIndex(county, config);
  console.log(`[tentatives bg] bulk scan: ${landingUrls.length} pages, ${captures.urlKeys.size} URLs already in manifest`);

  let scanTab;
  try {
    scanTab = await chrome.tabs.create({ url: landingUrls[0], active: false });
  } catch (e) {
    throw new Error(`could not open scan tab: ${e.message || e}`);
  }
  const tabId = scanTab.id;
  const pageRetryCounts = new Map();

  try {
    for (let i = 0; i < landingUrls.length; i++) {
      if (!(await bulkScanCheckpoint(control))) break;
      const url = landingUrls[i];
      const title = landingTitle(url);
      const retryCount = pageRetryCounts.get(url) || 0;
      port.postMessage({
        type: "page-start",
        index: i,
        total: landingUrls.length,
        url,
        title,
        attempt: retryCount + 1,
        maxAttempts: BULK_SCAN_MAX_PAGE_RETRIES + 1,
      });

      try {
        // Skip the navigation for the first page since chrome.tabs.create
        // already pointed there; just wait for it to finish loading. For
        // subsequent pages, give Chrome a moment to flip status from
        // "complete" (previous page) to "loading" — otherwise the poll
        // below could see stale "complete" and return prematurely.
        if (i > 0 || retryCount > 0) {
          await chrome.tabs.update(tabId, { url });
          if (!(await controlledBulkScanDelay(300, control))) break;
        }
        const loaded = await waitForTabComplete(tabId, { control });
        if (!loaded) break;
        if (delayMs > 0 && !(await controlledBulkScanDelay(delayMs, control))) break;
        if (!(await bulkScanCheckpoint(control))) break;

        const pdfs = await harvestFromTab(tabId);
        const pageSnapshots = await harvestPageSnapshotsFromTab(tabId);
        const layoutDocs = await harvestLayoutDocsFromTab(tabId);
        pdfs.sort((a, b) => (a.filename || a.url).localeCompare(b.filename || b.url));
        pageRetryCounts.delete(url);
        port.postMessage({
          type: "page-harvested",
          index: i,
          url,
          title,
          pdfCount: pdfs.length,
          pageSnapshotCount: pageSnapshots.length,
          layoutCount: layoutDocs.length,
        });

        for (const layoutDoc of layoutDocs) {
          if (!(await bulkScanCheckpoint(control))) break;
          let result;
          try {
            const r = await uploadOrSkipLayoutDoc(layoutDoc, county, config, layoutCaptures);
            result = { ...layoutDoc, ...r };
            if (r.status === "layout-captured") {
              await controlledBulkScanDelay(COMMIT_THROTTLE_MS, control);
            }
          } catch (e) {
            console.error("[tentatives bg] layout capture error for", layoutDoc.url, e);
            result = {
              ...layoutDoc,
              status: "error",
              filename: layoutDoc.title || layoutDoc.url || "layout snapshot",
              error: String(e.message || e),
            };
          }
          try {
            port.postMessage({ type: "result", result, pageIndex: i, pageTitle: title });
          } catch {
            console.warn("[tentatives bg] popup disconnected; finishing silently");
          }
        }

        for (const page of pageSnapshots) {
          if (!(await bulkScanCheckpoint(control))) break;
          let result;
          try {
            const r = await uploadOrSkipPageSnapshot(page, county, config, pageCaptures);
            result = { ...page, ...r };
            if (r.status === "page-captured") {
              await controlledBulkScanDelay(COMMIT_THROTTLE_MS, control);
            }
          } catch (e) {
            console.error("[tentatives bg] page snapshot error for", page.url, e);
            result = {
              ...page,
              status: "error",
              filename: page.title || page.url || "page snapshot",
              error: String(e.message || e),
            };
          }
          try {
            port.postMessage({ type: "result", result, pageIndex: i, pageTitle: title });
          } catch {
            console.warn("[tentatives bg] popup disconnected; finishing silently");
          }
        }

        for (const pdf of pdfs) {
          if (!(await bulkScanCheckpoint(control))) break;
          let result;
          try {
            const r = await uploadOrSkipPdf(pdf, county, config, captures);
            result = { ...pdf, ...r };
            if (r.status === "uploaded") {
              await controlledBulkScanDelay(COMMIT_THROTTLE_MS, control);
            }
          } catch (e) {
            console.error("[tentatives bg] bulk upload error for", pdf.filename, e);
            result = { ...pdf, status: "error", error: String(e.message || e) };
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
        if (control.cancel) break;
        const error = String(e.message || e);
        if (retryCount < BULK_SCAN_MAX_PAGE_RETRIES) {
          const nextRetryCount = retryCount + 1;
          pageRetryCounts.set(url, nextRetryCount);
          console.warn(`[tentatives bg] bulk scan page ${url} failed; retrying:`, e);
          try {
            port.postMessage({
              type: "page-retry",
              index: i,
              total: landingUrls.length,
              url,
              title,
              retry: nextRetryCount,
              maxRetries: BULK_SCAN_MAX_PAGE_RETRIES,
              error,
            });
          } catch { /* port closed */ }
          if (!(await controlledBulkScanDelay(BULK_SCAN_RETRY_DELAY_MS, control))) break;
          i -= 1;
          continue;
        }
        pageRetryCounts.delete(url);
        console.error(`[tentatives bg] bulk scan page ${url} failed:`, e);
        try {
          port.postMessage({
            type: "page-error",
            index: i,
            url,
            title,
            error,
          });
        } catch { /* port closed */ }
      }
    }
  } finally {
    try { await chrome.tabs.remove(tabId); } catch { /* already gone */ }
  }

  try {
    port.postMessage({ type: "done", reason: control.cancel ? "stopped" : "completed" });
  } catch { /* port closed */ }
  if (bulkScanControl === control) bulkScanControl = null;
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
        stopBulkScan(bulkScanControl);
        return;
      }
      if (msg.type === "pause") {
        setBulkScanPaused(bulkScanControl, true);
        return;
      }
      if (msg.type === "resume") {
        setBulkScanPaused(bulkScanControl, false);
        return;
      }
      if (msg.type !== "start") return;
      try {
        await scanAllStreaming({
          county: msg.county,
          port,
          explicitUrls: Array.isArray(msg.urls) ? msg.urls : null,
        });
      } catch (e) {
        console.error("[tentatives bg] bulk scan fatal", e);
        if (bulkScanControl?.port === port) bulkScanControl = null;
        try {
          port.postMessage({ type: "error", error: String(e.message || e) });
        } catch { /* port closed */ }
      }
    });
    return;
  }
});

chrome.runtime.onMessage.addListener((msg, sender, _sendResponse) => {
  console.log("[tentatives bg] message", msg?.type);
  if (msg && msg.type === "page-loaded") {
    const text = msg.pdfs.length ? String(msg.pdfs.length) : "";
    // Per-tab badge: a global setBadgeText would overwrite badges on other
    // tabs as the user moves around. tabId comes from the content-script sender.
    const tabId = sender?.tab?.id;
    const colorOpts = { color: msg.pdfs.length ? "#3b82f6" : "#9ca3af" };
    if (tabId !== undefined) {
      chrome.action.setBadgeText({ text, tabId });
      chrome.action.setBadgeBackgroundColor({ ...colorOpts, tabId });
    } else {
      chrome.action.setBadgeText({ text });
      chrome.action.setBadgeBackgroundColor(colorOpts);
    }
  }
});

// On install / update: pre-seed GitHub config so a fresh install only needs a
// PAT — the canonical repo is aimesy/tentatives@master and there's no reason
// to make every user type that in. Existing values are preserved.
async function seedDefaults() {
  const stored = await chrome.storage.local.get([
    "githubOwner", "githubRepo", "githubBranch",
  ]);
  const updates = {};
  if (!stored.githubOwner)  updates.githubOwner  = DEFAULT_GITHUB.owner;
  if (!stored.githubRepo)   updates.githubRepo   = DEFAULT_GITHUB.repo;
  if (!stored.githubBranch) updates.githubBranch = DEFAULT_GITHUB.branch;
  if (Object.keys(updates).length) {
    await chrome.storage.local.set(updates);
    console.log("[tentatives bg] seeded defaults:", updates);
  }
}

// Chrome 116+: clicking the action icon opens the side panel. Older Chrome
// users get the default behavior (no popup), which on Chromium means the user
// has to open the side panel from the toolbar menu — fine as a fallback.
async function setupSidePanel() {
  if (chrome.sidePanel?.setPanelBehavior) {
    try {
      await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
    } catch (e) {
      console.warn("[tentatives bg] sidePanel.setPanelBehavior failed:", e);
    }
  }
}

// Firefox uses browser.sidebarAction; clicking the toolbar action there can
// toggle the sidebar. globalThis.browser is defined in Firefox but not Chrome.
if (typeof globalThis.browser !== "undefined" && globalThis.browser.sidebarAction?.toggle) {
  chrome.action.onClicked.addListener(async () => {
    try { await globalThis.browser.sidebarAction.toggle(); }
    catch (e) { console.warn("[tentatives bg] sidebarAction.toggle failed:", e); }
  });
}

chrome.runtime.onInstalled.addListener(async (details) => {
  console.log("[tentatives bg] installed", details.reason);
  await seedDefaults();
  await setupSidePanel();
});

// Also run once on service-worker startup so updates / reloads pick up the
// side-panel behavior without waiting for the next onInstalled.
setupSidePanel();
