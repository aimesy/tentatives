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

async function getConfig() {
  const {
    githubToken = "",
    githubOwner = "",
    githubRepo = "",
    githubBranch = "",
  } = await chrome.storage.local.get([
    "githubToken",
    "githubOwner",
    "githubRepo",
    "githubBranch",
  ]);
  return { githubToken, githubOwner, githubRepo, githubBranch };
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

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "upload") return;
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
