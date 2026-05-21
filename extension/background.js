// Background service worker. Receives upload requests from the sidebar,
// fetches PDFs (with host_permissions, no CORS issue), hashes them, checks
// GitHub for existence, uploads new ones via the Contents API, and appends
// a row to captures.ndjson.

import { sha256Hex, bufferToBase64 } from "./lib/hash.js";
import {
  base64ToText,
  fileExists,
  getFile,
  putFile,
  appendNdjsonLine,
  appendNdjsonFileBatch,
} from "./lib/github.js";
import {
  COUNTY_SCAN,
  DEFAULT_GITHUB,
  VOLATILE_URL_COUNTIES,
} from "./lib/counties.js";

const DEFAULT_PAGE_LOAD_DELAY_MS = 5000;
const BULK_SCAN_MAX_PAGE_RETRIES = 3;
const BULK_SCAN_RETRY_DELAY_MS = 1000;
const SHELL_SCAN_DEFAULT_MAX_TABS = 4;
const SHELL_SCAN_MAX_TABS = 8;
const MAX_PDF_BYTES = 64 * 1024 * 1024;
const CAPTURE_INDEX_CACHE_TTL_MS = 15000;
const PDF_CONTENT_TYPES = new Set([
  "application/pdf",
  "application/x-pdf",
  "application/octet-stream",
  "binary/octet-stream",
]);

const captureIndexCache = new Map();

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

function requireHttpsUrl(rawUrl) {
  let url;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error(`invalid PDF URL: ${rawUrl || "(blank)"}`);
  }
  if (url.protocol !== "https:") {
    throw new Error(`refusing non-HTTPS PDF URL: ${url.href}`);
  }
  if (url.username || url.password) {
    throw new Error(`refusing PDF URL with credentials: ${url.origin}${url.pathname}`);
  }
  return url.href;
}

function hostMatches(host, expectedHost) {
  const h = String(host || "").toLowerCase();
  const expected = String(expectedHost || "").toLowerCase();
  const expectedNoWww = expected.startsWith("www.") ? expected.slice(4) : expected;
  const hostNoWww = h.startsWith("www.") ? h.slice(4) : h;
  return h === expected
    || h.endsWith(`.${expected}`)
    || hostNoWww === expectedNoWww;
}

function validatePdfRedirect(requestedUrl, finalUrl, sourceUrl = null) {
  const requested = new URL(requestedUrl);
  const final = new URL(finalUrl);
  let source = null;
  try {
    source = sourceUrl ? new URL(sourceUrl) : null;
  } catch { /* ignore invalid source URL; fetch URL validation handles requested/final */ }
  if (
    !hostMatches(final.hostname, requested.hostname)
    && (!source || !hostMatches(final.hostname, source.hostname))
  ) {
    throw new Error(`fetch ${requestedUrl}: redirected to untrusted host ${final.hostname}`);
  }
}

function validatePdfContentType(resp, fetchUrl) {
  const raw = resp.headers.get("content-type") || "";
  const type = raw.split(";")[0].trim().toLowerCase();
  if (type && !PDF_CONTENT_TYPES.has(type)) {
    throw new Error(`fetch ${fetchUrl}: expected PDF content-type, got ${raw}`);
  }
}

function validatePdfContentLength(resp, fetchUrl) {
  const raw = resp.headers.get("content-length");
  if (!raw) return;
  const length = Number(raw);
  if (Number.isFinite(length) && length > MAX_PDF_BYTES) {
    throw new Error(`fetch ${fetchUrl}: PDF too large (${length} bytes)`);
  }
}

async function readArrayBufferWithLimit(resp, maxBytes, fetchUrl) {
  if (!resp.body?.getReader) {
    const buffer = await resp.arrayBuffer();
    if (buffer.byteLength > maxBytes) {
      throw new Error(`fetch ${fetchUrl}: PDF too large (${buffer.byteLength} bytes)`);
    }
    return buffer;
  }

  const reader = resp.body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      try { await reader.cancel(); } catch { /* ignore */ }
      throw new Error(`fetch ${fetchUrl}: PDF too large (>${maxBytes} bytes)`);
    }
    chunks.push(value);
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes.buffer;
}

function hasPdfMagic(buffer) {
  const bytes = new Uint8Array(buffer, 0, Math.min(buffer.byteLength, 1024));
  for (let i = 0; i <= bytes.length - 5; i++) {
    if (
      bytes[i] === 0x25
      && bytes[i + 1] === 0x50
      && bytes[i + 2] === 0x44
      && bytes[i + 3] === 0x46
      && bytes[i + 4] === 0x2d
    ) {
      return true;
    }
  }
  return false;
}

async function fetchAndHashPdf(pdf) {
  const requestedUrl = requireHttpsUrl(pdf.fetchUrl || pdf.fetch_url || pdf.url);
  const resp = await fetch(requestedUrl, {
    credentials: "omit",
    redirect: "follow",
  });
  const fetchUrl = requireHttpsUrl(resp.url || requestedUrl);
  validatePdfRedirect(requestedUrl, fetchUrl, pdf.url);
  if (!resp.ok) throw new Error(`fetch ${fetchUrl}: HTTP ${resp.status}`);
  validatePdfContentType(resp, fetchUrl);
  validatePdfContentLength(resp, fetchUrl);
  const buffer = await readArrayBufferWithLimit(resp, MAX_PDF_BYTES, fetchUrl);
  if (!hasPdfMagic(buffer)) {
    throw new Error(`fetch ${fetchUrl}: response did not start with PDF magic`);
  }
  const sha = await sha256Hex(buffer);
  return {
    fetchUrl,
    buffer,
    sha,
    size: buffer.byteLength,
  };
}

async function uploadOnePdf(pdf, config, fetchedPdf = null, options = {}) {
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
  // We always log a capture event though - re-visits are meaningful provenance.
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

  // 3. Append a capture event to captures.ndjson (always - even when PDF was
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
  const capturePath = `archive/${county}/captures.ndjson`;
  if (options.captureBatch) {
    options.captureBatch.add(
      capturePath,
      JSON.stringify(capture),
      `${county}: log PDF captures`,
    );
  } else {
    await appendNdjsonLine({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: capturePath,
      newLine: JSON.stringify(capture),
      message: `${county}: log capture ${filename}`,
      token: githubToken,
    });
    invalidateIndexCache(config, county, "captures.ndjson");
  }

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

function cloneCaptureIndex(index) {
  const clone = emptyCaptureIndex();
  for (const key of index.urlKeys) clone.urlKeys.add(key);
  for (const [key, shas] of index.shaByUrlKey) {
    clone.shaByUrlKey.set(key, new Set(shas));
  }
  return clone;
}

function cloneSet(set) {
  return new Set(set);
}

function indexCacheKey(config, county, filename) {
  return [
    config.githubOwner || "",
    config.githubRepo || "",
    config.githubBranch || "",
    county || "",
    filename || "",
  ].join("\n");
}

function getCachedIndex(key, cloneValue) {
  const cached = captureIndexCache.get(key);
  if (!cached || cached.expiresAt <= Date.now()) {
    captureIndexCache.delete(key);
    return null;
  }
  return cloneValue(cached.value);
}

function setCachedIndex(key, value) {
  captureIndexCache.set(key, {
    value,
    expiresAt: Date.now() + CAPTURE_INDEX_CACHE_TTL_MS,
  });
}

function invalidateIndexCache(config, county, filename) {
  captureIndexCache.delete(indexCacheKey(config, county, filename));
}

function parseNdjsonRows(content, label) {
  const rows = [];
  let parseErrors = 0;
  const samples = [];
  const lines = String(content || "").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (!trimmed) continue;
    try {
      rows.push(JSON.parse(trimmed));
    } catch (e) {
      parseErrors += 1;
      if (samples.length < 3) {
        samples.push(`line ${i + 1}: ${e.message || e}`);
      }
    }
  }
  if (parseErrors > 0) {
    console.warn(
      `[tentatives bg] ${label}: skipped ${parseErrors} malformed NDJSON line(s)`,
      samples,
    );
  }
  return rows;
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
  const cacheKey = indexCacheKey(config, county, "captures.ndjson");
  const cached = getCachedIndex(cacheKey, cloneCaptureIndex);
  if (cached) return cached;
  try {
    const f = await getFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: `archive/${county}/captures.ndjson`,
      token: githubToken,
    });
    const content = base64ToText(f.content);
    const index = emptyCaptureIndex();
    for (const row of parseNdjsonRows(content, `archive/${county}/captures.ndjson`)) {
      if (row.source_url) {
        rememberCapture(index, row.source_url, row.wayback_ts, row.source_sha256);
      }
    }
    setCachedIndex(cacheKey, cloneCaptureIndex(index));
    return cloneCaptureIndex(index);
  } catch (e) {
    if (e.status === 404) return emptyCaptureIndex();
    console.warn("[tentatives bg] could not load captures.ndjson:", e.message);
    return emptyCaptureIndex();
  }
}

function captureKey(url, waybackTs = null) {
  return `${url}::${waybackTs || ""}`;
}

async function uploadOrSkipPdf(pdf, county, config, captures, options = {}) {
  const waybackTs = pdf.waybackTs || pdf.wayback_ts || null;
  const key = captureKey(pdf.url, waybackTs);

  if (!VOLATILE_URL_COUNTIES.has(county)) {
    if (captures.urlKeys.has(key)) {
      return { status: "already-captured" };
    }
    const result = await uploadOnePdf({ ...pdf, county }, config, null, options);
    if (options.captureBatch) {
      options.captureBatch.afterFlush(() => rememberCapture(captures, pdf.url, waybackTs, result.sha));
    } else {
      rememberCapture(captures, pdf.url, waybackTs, result.sha);
    }
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

  const result = await uploadOnePdf({ ...pdf, county }, config, fetched, options);
  if (options.captureBatch) {
    options.captureBatch.afterFlush(() => rememberCapture(captures, pdf.url, waybackTs, result.sha));
  } else {
    rememberCapture(captures, pdf.url, waybackTs, result.sha);
  }
  return result;
}

function pageCaptureKey(url, sha) {
  return `${url || ""}::${sha || ""}`;
}

async function loadArtifactCaptureIndex(county, config, filename) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  const keys = new Set();
  if (!githubToken || !githubOwner || !githubRepo) return keys;
  const cacheKey = indexCacheKey(config, county, filename);
  const cached = getCachedIndex(cacheKey, cloneSet);
  if (cached) return cached;
  try {
    const f = await getFile({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: `archive/${county}/${filename}`,
      token: githubToken,
    });
    const content = base64ToText(f.content);
    for (const row of parseNdjsonRows(content, `archive/${county}/${filename}`)) {
      const sha = row.source_sha256 || row.layout_sha256;
      if (row.source_url && sha) {
        keys.add(pageCaptureKey(row.source_url, sha));
      }
    }
    setCachedIndex(cacheKey, cloneSet(keys));
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

async function uploadOrSkipPageSnapshot(snapshot, county, config, pageCaptures, options = {}) {
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
  const capturePath = `archive/${county}/page-captures.ndjson`;
  if (options.captureBatch) {
    options.captureBatch.add(
      capturePath,
      JSON.stringify(capture),
      `${county}: log page captures`,
    );
  } else {
    await appendNdjsonLine({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: capturePath,
      newLine: JSON.stringify(capture),
      message: `${county}: log page capture ${sha.slice(0, 8)}`,
      token: githubToken,
    });
    invalidateIndexCache(config, county, "page-captures.ndjson");
  }
  if (options.captureBatch) {
    options.captureBatch.afterFlush(() => pageCaptures.add(key));
  } else {
    pageCaptures.add(key);
  }
  return {
    status: exists ? "page-logged" : "page-captured",
    sha,
    archivePath,
    size: bytes.byteLength,
    filename,
    url: sourceUrl,
  };
}

async function uploadOrSkipLayoutDoc(layoutDoc, county, config, layoutCaptures, options = {}) {
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
  const capturePath = `archive/${county}/layout-captures.ndjson`;
  if (options.captureBatch) {
    options.captureBatch.add(
      capturePath,
      JSON.stringify(capture),
      `${county}: log layout captures`,
    );
  } else {
    await appendNdjsonLine({
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch,
      path: capturePath,
      newLine: JSON.stringify(capture),
      message: `${county}: log layout capture ${sha.slice(0, 8)}`,
      token: githubToken,
    });
    invalidateIndexCache(config, county, "layout-captures.ndjson");
  }
  if (options.captureBatch) {
    options.captureBatch.afterFlush(() => layoutCaptures.add(key));
  } else {
    layoutCaptures.add(key);
  }
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

function createCaptureBatch(config, county) {
  const { githubToken, githubOwner, githubRepo, githubBranch } = config;
  const entries = new Map();
  const afterFlushCallbacks = [];
  return {
    add(path, line, message) {
      let entry = entries.get(path);
      if (!entry) {
        entry = { lines: [], message };
        entries.set(path, entry);
      }
      entry.lines.push(line);
    },
    afterFlush(callback) {
      afterFlushCallbacks.push(callback);
    },
    async flush() {
      let count = 0;
      const files = [];
      for (const [path, entry] of entries) {
        if (!entry.lines.length) continue;
        files.push({ path, newLines: entry.lines });
        count += entry.lines.length;
      }
      if (files.length) {
        await appendNdjsonFileBatch({
          owner: githubOwner,
          repo: githubRepo,
          branch: githubBranch,
          files,
          message: `${county}: log scan capture manifests (${count})`,
          token: githubToken,
        });
      }
      for (const path of entries.keys()) {
        const filename = path.split("/").pop();
        if (filename) invalidateIndexCache(config, county, filename);
      }
      for (const callback of afterFlushCallbacks) callback();
      afterFlushCallbacks.length = 0;
      entries.clear();
      return count;
    },
  };
}

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
      // Popup closed mid-upload - keep going but stop streaming.
      console.warn("[tentatives bg] popup disconnected; finishing silently");
      return;
    }
  }
  try {
    port.postMessage({ type: "done" });
  } catch { /* popup closed */ }
}

async function uploadScanArtifacts({
  county,
  config,
  captures,
  pageCaptures,
  layoutCaptures,
  pdfs,
  pageSnapshots,
  layoutDocs,
  control,
  postResult,
}) {
  const captureBatch = createCaptureBatch(config, county);
  const results = [];
  let archiveCommitCount = 0;

  for (const layoutDoc of layoutDocs) {
    if (!(await bulkScanCheckpoint(control))) break;
    let result;
    try {
      const r = await uploadOrSkipLayoutDoc(layoutDoc, county, config, layoutCaptures, {
        captureBatch,
      });
      result = { ...layoutDoc, ...r };
      if (r.status === "layout-captured") archiveCommitCount += 1;
    } catch (e) {
      console.error("[tentatives bg] layout capture error for", layoutDoc.url, e);
      result = {
        ...layoutDoc,
        status: "error",
        filename: layoutDoc.title || layoutDoc.url || "layout snapshot",
        error: String(e.message || e),
      };
    }
    results.push(result);
  }

  for (const page of pageSnapshots) {
    if (!(await bulkScanCheckpoint(control))) break;
    let result;
    try {
      const r = await uploadOrSkipPageSnapshot(page, county, config, pageCaptures, {
        captureBatch,
      });
      result = { ...page, ...r };
      if (r.status === "page-captured") archiveCommitCount += 1;
    } catch (e) {
      console.error("[tentatives bg] page snapshot error for", page.url, e);
      result = {
        ...page,
        status: "error",
        filename: page.title || page.url || "page snapshot",
        error: String(e.message || e),
      };
    }
    results.push(result);
  }

  for (const pdf of pdfs) {
    if (!(await bulkScanCheckpoint(control))) break;
    let result;
    try {
      const r = await uploadOrSkipPdf(pdf, county, config, captures, {
        captureBatch,
      });
      result = { ...pdf, ...r };
      if (r.status === "uploaded") archiveCommitCount += 1;
    } catch (e) {
      console.error("[tentatives bg] scan upload error for", pdf.filename, e);
      result = { ...pdf, status: "error", error: String(e.message || e) };
    }
    results.push(result);
  }

  const captureCommitCount = await captureBatch.flush();
  if (archiveCommitCount + captureCommitCount > 0) {
    await controlledBulkScanDelay(COMMIT_THROTTLE_MS, control);
  }

  for (const result of results) {
    postResult(result);
  }

  return bulkScanCheckpoint(control);
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

async function waitForMainFrameCommit(tabId, { timeoutMs = 15000 } = {}) {
  if (!chrome.webNavigation?.onCommitted) return true;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error(`tab navigation commit timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    const listener = (details) => {
      if (details.tabId !== tabId || details.frameId !== 0) return;
      cleanup();
      resolve(true);
    };
    const cleanup = () => {
      clearTimeout(timer);
      try { chrome.webNavigation.onCommitted.removeListener(listener); } catch { /* ignore */ }
    };
    chrome.webNavigation.onCommitted.addListener(listener);
  });
}

async function navigateScanTab(tabId, url, control) {
  const committed = waitForMainFrameCommit(tabId);
  await chrome.tabs.update(tabId, { url });
  await committed;
  return bulkScanCheckpoint(control);
}

// Polls chrome.tabs.get for status="complete". The navigation helpers above
// wait for a fresh main-frame commit first; this loop then waits for that page
// to finish loading and keeps the MV3 service worker alive through chrome API
// calls.
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

// Set by the side panel via pause/resume/stop messages. Controls are keyed by
// port so parallel side-panel sessions cannot overwrite each other.
const bulkScanControls = new Map();
const shellScanControls = new Map();

function createBulkScanControl(port) {
  return {
    cancel: false,
    paused: false,
    port,
    resumeWaiters: new Set(),
    disconnectListener: null,
  };
}

function registerScanControl(controlMap, port, control) {
  const previous = controlMap.get(port);
  if (previous && previous !== control) {
    stopBulkScan(previous);
    clearScanControl(controlMap, port, previous);
  }
  const disconnectListener = () => stopBulkScan(control);
  control.disconnectListener = disconnectListener;
  port.onDisconnect.addListener(disconnectListener);
  controlMap.set(port, control);
  return control;
}

function clearScanControl(controlMap, port, control) {
  if (!control) {
    controlMap.delete(port);
    return;
  }
  if (controlMap.get(port) === control) controlMap.delete(port);
  if (control.disconnectListener) {
    try { port.onDisconnect.removeListener(control.disconnectListener); } catch { /* ignore */ }
    control.disconnectListener = null;
  }
}

function scanControlFor(controlMap, port) {
  return controlMap.get(port) || null;
}

function stopAndClearScanControl(controlMap, port) {
  const control = scanControlFor(controlMap, port);
  if (!control) return;
  stopBulkScan(control);
  clearScanControl(controlMap, port, control);
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
  const control = registerScanControl(bulkScanControls, port, createBulkScanControl(port));
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
    clearScanControl(bulkScanControls, port, control);
    return;
  }
  port.postMessage({ type: "landings", urls: landingUrls });
  if (landingUrls.length === 0) {
    port.postMessage({ type: "done", reason: "no-landings" });
    clearScanControl(bulkScanControls, port, control);
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
        // "complete" (previous page) to "loading" - otherwise the poll
        // below could see stale "complete" and return prematurely.
        if (i > 0 || retryCount > 0) {
          if (!(await navigateScanTab(tabId, url, control))) break;
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

            // Keep going even if popup closed - the bulk scan is long-running
        const ok = await uploadScanArtifacts({
          county,
          config,
          captures,
          pageCaptures,
          layoutCaptures,
          pdfs,
          pageSnapshots,
          layoutDocs,
          control,
          postResult: (result) => {
            if (!postBulkScanMessage(port, { type: "result", result, pageIndex: i, pageTitle: title })) {
              console.warn("[tentatives bg] popup disconnected; finishing silently");
            }
          },
        });
        if (!ok) break;
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
  clearScanControl(bulkScanControls, port, control);
}

// ========================================================= SHELL SCAN
//
// A parallel browser pass across selected counties. Each worker owns one tab
// and walks one county at a time, so GitHub writes stay serialized per county
// while multiple courts can load and capture at once.

function createShellScanControl(port) {
  return {
    ...createBulkScanControl(port),
    openTabs: new Set(),
  };
}

function normalizedShellCounties(counties) {
  const seen = new Set();
  const out = [];
  for (const county of counties || []) {
    if (!COUNTY_SCAN[county] || seen.has(county)) continue;
    seen.add(county);
    out.push(county);
  }
  return out;
}

function normalizeShellMaxTabs(value, countyCount) {
  const parsed = Number(value);
  const requested = Number.isFinite(parsed) && parsed > 0
    ? Math.floor(parsed)
    : SHELL_SCAN_DEFAULT_MAX_TABS;
  return Math.max(1, Math.min(SHELL_SCAN_MAX_TABS, countyCount || 1, requested));
}

async function detectHumanIntervention(tabId) {
  let results;
  try {
    results = await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func: () => {
        const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
        const href = clean(location.href);
        const title = clean(document.title);
        const body = clean(document.body?.innerText || document.documentElement?.innerText || "").slice(0, 12000);
        const haystack = `${href}\n${title}\n${body}`.toLowerCase();
        const checks = [
          [/captcha/, "captcha challenge"],
          [/verify (that )?you are human/, "human verification"],
          [/are you (a )?human/, "human verification"],
          [/checking (your )?browser/, "browser check"],
          [/security check/, "security check"],
          [/cloudflare/, "browser security challenge"],
          [/access denied/, "access denied"],
          [/too many requests/, "rate limit"],
          [/temporarily blocked/, "temporary block"],
          [/unusual traffic/, "unusual traffic check"],
          [/enable cookies/, "cookie check"],
          [/(login|required|must) sign in/, "login required"],
        ];
        for (const [pattern, reason] of checks) {
          if (pattern.test(haystack)) {
            return { reason, url: href, title };
          }
        }
        return null;
      },
    });
  } catch (e) {
    console.warn("[tentatives bg] human-check detection failed:", e);
    return null;
  }
  for (const res of results || []) {
    if (res?.result?.reason) return res.result;
  }
  return null;
}

async function activateShellTab(tabId) {
  try {
    await chrome.tabs.update(tabId, { active: true });
  } catch { /* tab may have closed */ }
}

async function ensureShellPageReady(control, tabId, context, delayMs) {
  while (!control.cancel) {
    const signal = await detectHumanIntervention(tabId);
    if (!signal) return true;
    control.paused = true;
    await activateShellTab(tabId);
    postBulkScanMessage(control.port, {
      type: "human-pause",
      county: context.county,
      url: signal.url || context.url,
      title: signal.title || context.title,
      reason: signal.reason,
    });
    postBulkScanMessage(control.port, {
      type: "control-state",
      paused: true,
      human: true,
      reason: signal.reason,
    });
    await waitForBulkScanResume(control);
    if (control.cancel) return false;
    try {
      await waitForTabComplete(tabId, { control, timeoutMs: 15000 });
    } catch { /* the user may still be mid-intervention; recheck below */ }
    if (delayMs > 0 && !(await controlledBulkScanDelay(Math.min(delayMs, 1500), control))) {
      return false;
    }
  }
  return false;
}

async function shellScanCounty({ county, config, delayMs, control, workerIndex }) {
  postBulkScanMessage(control.port, {
    type: "county-start",
    county,
    workerIndex,
    phase: "discovering",
  });
  const landingUrls = await discoverLandingPages(county);
  postBulkScanMessage(control.port, {
    type: "county-landings",
    county,
    workerIndex,
    urls: landingUrls,
  });
  if (landingUrls.length === 0 || !(await bulkScanCheckpoint(control))) {
    return { pages: 0 };
  }

  const captures = await loadCaptureIndex(county, config);
  const pageCaptures = await loadPageCaptureIndex(county, config);
  const layoutCaptures = await loadLayoutCaptureIndex(county, config);

  let scanTab;
  try {
    scanTab = await chrome.tabs.create({ url: landingUrls[0], active: false });
  } catch (e) {
    throw new Error(`could not open shell tab: ${e.message || e}`);
  }
  const tabId = scanTab.id;
  control.openTabs.add(tabId);
  const pageRetryCounts = new Map();
  let pagesCompleted = 0;

  try {
    for (let i = 0; i < landingUrls.length; i++) {
      if (!(await bulkScanCheckpoint(control))) break;
      const url = landingUrls[i];
      const title = landingTitle(url);
      const retryCount = pageRetryCounts.get(url) || 0;
      postBulkScanMessage(control.port, {
        type: "page-start",
        county,
        workerIndex,
        index: i,
        total: landingUrls.length,
        url,
        title,
        attempt: retryCount + 1,
        maxAttempts: BULK_SCAN_MAX_PAGE_RETRIES + 1,
      });

      try {
        if (i > 0 || retryCount > 0) {
          if (!(await navigateScanTab(tabId, url, control))) break;
        }
        const loaded = await waitForTabComplete(tabId, { control });
        if (!loaded) break;
        if (delayMs > 0 && !(await controlledBulkScanDelay(delayMs, control))) break;
        if (!(await ensureShellPageReady(control, tabId, { county, url, title }, delayMs))) break;
        if (!(await bulkScanCheckpoint(control))) break;

        const pdfs = await harvestFromTab(tabId);
        const pageSnapshots = await harvestPageSnapshotsFromTab(tabId);
        const layoutDocs = await harvestLayoutDocsFromTab(tabId);
        pdfs.sort((a, b) => (a.filename || a.url).localeCompare(b.filename || b.url));
        pageRetryCounts.delete(url);
        pagesCompleted += 1;
        postBulkScanMessage(control.port, {
          type: "page-harvested",
          county,
          workerIndex,
          index: i,
          url,
          title,
          pdfCount: pdfs.length,
          pageSnapshotCount: pageSnapshots.length,
          layoutCount: layoutDocs.length,
        });

        const ok = await uploadScanArtifacts({
          county,
          config,
          captures,
          pageCaptures,
          layoutCaptures,
          pdfs,
          pageSnapshots,
          layoutDocs,
          control,
          postResult: (result) => postBulkScanMessage(control.port, {
            type: "result",
            result: { ...result, county },
            pageIndex: i,
            pageTitle: title,
            county,
          }),
        });
        if (!ok) break;
      } catch (e) {
        if (control.cancel) break;
        const error = String(e.message || e);
        if (retryCount < BULK_SCAN_MAX_PAGE_RETRIES) {
          const nextRetryCount = retryCount + 1;
          pageRetryCounts.set(url, nextRetryCount);
          console.warn(`[tentatives bg] shell scan page ${url} failed; retrying:`, e);
          postBulkScanMessage(control.port, {
            type: "page-retry",
            county,
            workerIndex,
            index: i,
            total: landingUrls.length,
            url,
            title,
            retry: nextRetryCount,
            maxRetries: BULK_SCAN_MAX_PAGE_RETRIES,
            error,
          });
          if (!(await controlledBulkScanDelay(BULK_SCAN_RETRY_DELAY_MS, control))) break;
          i -= 1;
          continue;
        }
        pageRetryCounts.delete(url);
        pagesCompleted += 1;
        console.error(`[tentatives bg] shell scan page ${url} failed:`, e);
        postBulkScanMessage(control.port, {
          type: "page-error",
          county,
          workerIndex,
          index: i,
          url,
          title,
          error,
        });
      }
    }
  } finally {
    control.openTabs.delete(tabId);
    try { await chrome.tabs.remove(tabId); } catch { /* already gone */ }
  }

  return { pages: pagesCompleted };
}

async function shellScanStreaming({ counties, port, maxTabs = SHELL_SCAN_DEFAULT_MAX_TABS }) {
  const selectedCounties = normalizedShellCounties(counties);
  const control = registerScanControl(shellScanControls, port, createShellScanControl(port));
  const config = await getConfig();
  if (!config.githubToken || !config.githubOwner || !config.githubRepo) {
    throw new Error(
      "Extension not configured. Open the options page and set GitHub PAT / owner / repo.",
    );
  }
  if (selectedCounties.length === 0) {
    port.postMessage({ type: "done", reason: "no-counties" });
    clearScanControl(shellScanControls, port, control);
    return;
  }

  const delayMs = Number.isFinite(+config.pageLoadDelayMs)
    ? Math.max(0, +config.pageLoadDelayMs)
    : DEFAULT_PAGE_LOAD_DELAY_MS;
  const concurrency = normalizeShellMaxTabs(maxTabs, selectedCounties.length);
  port.postMessage({
    type: "queue",
    counties: selectedCounties,
    concurrency,
  });

  let nextCountyIndex = 0;
  let completedCounties = 0;

  const runWorker = async (workerIndex) => {
    while (!control.cancel) {
      if (!(await bulkScanCheckpoint(control))) break;
      const county = selectedCounties[nextCountyIndex++];
      if (!county) break;
      try {
        const result = await shellScanCounty({
          county,
          config,
          delayMs,
          control,
          workerIndex,
        });
        completedCounties += 1;
        postBulkScanMessage(port, {
          type: "county-done",
          county,
          workerIndex,
          pages: result.pages,
          completedCounties,
          totalCounties: selectedCounties.length,
        });
      } catch (e) {
        completedCounties += 1;
        console.error(`[tentatives bg] shell scan county ${county} failed:`, e);
        postBulkScanMessage(port, {
          type: "county-error",
          county,
          workerIndex,
          error: String(e.message || e),
          completedCounties,
          totalCounties: selectedCounties.length,
        });
      }
    }
  };

  try {
    await Promise.all(Array.from({ length: concurrency }, (_unused, i) => runWorker(i)));
  } finally {
    for (const tabId of [...control.openTabs]) {
      try { await chrome.tabs.remove(tabId); } catch { /* already gone */ }
    }
    control.openTabs.clear();
  }

  try {
    port.postMessage({ type: "done", reason: control.cancel ? "stopped" : "completed" });
  } catch { /* port closed */ }
  clearScanControl(shellScanControls, port, control);
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
    port.onDisconnect.addListener(() => stopAndClearScanControl(bulkScanControls, port));
    port.onMessage.addListener(async (msg) => {
      if (msg.type === "stop") {
        stopAndClearScanControl(bulkScanControls, port);
        return;
      }
      if (msg.type === "pause") {
        setBulkScanPaused(scanControlFor(bulkScanControls, port), true);
        return;
      }
      if (msg.type === "resume") {
        setBulkScanPaused(scanControlFor(bulkScanControls, port), false);
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
        clearScanControl(bulkScanControls, port, scanControlFor(bulkScanControls, port));
        try {
          port.postMessage({ type: "error", error: String(e.message || e) });
        } catch { /* port closed */ }
      }
    });
    return;
  }
  if (port.name === "shell-scan") {
    port.onDisconnect.addListener(() => stopAndClearScanControl(shellScanControls, port));
    port.onMessage.addListener(async (msg) => {
      if (msg.type === "stop") {
        stopAndClearScanControl(shellScanControls, port);
        return;
      }
      if (msg.type === "pause") {
        setBulkScanPaused(scanControlFor(shellScanControls, port), true);
        return;
      }
      if (msg.type === "resume") {
        setBulkScanPaused(scanControlFor(shellScanControls, port), false);
        return;
      }
      if (msg.type !== "start") return;
      try {
        await shellScanStreaming({
          counties: Array.isArray(msg.counties) ? msg.counties : [],
          port,
          maxTabs: msg.maxTabs,
        });
      } catch (e) {
        console.error("[tentatives bg] shell scan fatal", e);
        clearScanControl(shellScanControls, port, scanControlFor(shellScanControls, port));
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
// PAT - the canonical repo is aimesy/tentatives@master and there's no reason
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
// has to open the side panel from the toolbar menu - fine as a fallback.
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
