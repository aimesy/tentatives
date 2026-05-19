// Background service worker. Receives upload requests from the popup,
// fetches PDFs (with host_permissions, no CORS issue), hashes them, checks
// GitHub for existence, uploads new ones via the Contents API, and appends
// a row to captures.ndjson.

import { sha256Hex, bufferToBase64 } from "./lib/hash.js";
import {
  fileExists,
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

  // 2. Idempotency: skip if already in repo.
  const exists = await fileExists({
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch,
    path: archivePath,
    token: githubToken,
  });
  if (exists) {
    return { status: "skipped-exists", sha, archivePath };
  }

  // 3. PUT the PDF.
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

  // 4. Append a row to captures.ndjson.
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

  return { status: "uploaded", sha, archivePath, size: buffer.byteLength };
}

async function uploadBatch({ pdfs, county }) {
  const config = await getConfig();
  const results = [];
  for (const pdf of pdfs) {
    try {
      const r = await uploadOnePdf({ ...pdf, county }, config);
      results.push({ ...pdf, ...r });
    } catch (e) {
      results.push({ ...pdf, status: "error", error: String(e.message || e) });
    }
  }
  return results;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "upload-batch") {
    uploadBatch({ pdfs: msg.pdfs, county: msg.county })
      .then((results) => sendResponse({ ok: true, results }))
      .catch((e) => sendResponse({ ok: false, error: String(e.message || e) }));
    return true; // keep channel open for async response
  }
  if (msg && msg.type === "page-loaded") {
    // Could update badge with PDF count here; for v1 just acknowledge.
    chrome.action.setBadgeText({ text: String(msg.pdfs.length) });
    chrome.action.setBadgeBackgroundColor({ color: "#3b82f6" });
  }
});
