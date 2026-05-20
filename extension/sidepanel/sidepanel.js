// Side panel: active-tab capture plus per-county quick-fetch controls.
// Streams upload and scan progress from the background service worker.

import {
  COUNTY_LABEL,
  HOST_TO_COUNTY,
  COUNTY_SCAN,
  SIDEBAR_PAGES,
  DEFAULT_GITHUB,
} from "../lib/counties.js";

const $ = (id) => document.getElementById(id);

const hostEl = $("d-host");
const countyEl = $("d-county");
const countEl = $("d-pdfcount");
const connDot = $("conn-dot");
const connText = $("conn-text");

const statusLineEl = $("status-line");
const progressTextEl = $("progress-text");
const bulkStatusEl = $("bulk-status");

const uploadBtn = $("upload");
const rescanBtn = $("rescan");
const bulkStopBtn = $("bulk-stop");
const clearBtn = $("clear-activity");
const countyBlocks = $("county-blocks");

const list = $("results");
const progressBar = $("progress-bar");
const progressFill = $("progress-fill");

const archiveLink = $("archive-link");
const viewerLink = $("open-viewer");
const versionEl = $("ext-version");

const pageActionButtons = new Set();
const CONFIG_KEYS = new Set([
  "githubToken",
  "githubOwner",
  "githubRepo",
  "githubBranch",
]);

let busy = false;
let pendingRefreshAfterBusy = false;
let renderTimer = null;
let renderInFlight = false;
let renderAgain = false;

$("open-options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

function setPill(el, text, kind = "mute") {
  el.innerHTML = `<span class="pill ${kind}">${escapeHtml(text)}</span>`;
}

function setConn(kind, text) {
  connDot.className = `dot ${kind}`;
  connText.textContent = text;
}

function setPageActionsDisabled(disabled) {
  for (const btn of pageActionButtons) {
    btn.disabled = disabled || btn.dataset.configOk !== "true";
  }
}

function countyForUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase().replace(/\.$/, "");
    return HOST_TO_COUNTY[host] || null;
  } catch {
    return null;
  }
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function navigateActiveTab(url) {
  const tab = await activeTab();
  if (tab?.id) {
    await chrome.tabs.update(tab.id, { url });
  } else {
    await chrome.tabs.create({ url, active: true });
  }
  queueRender(500);
}

async function harvestFromTab(tabId) {
  try {
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
  } catch (e) {
    console.error("[tentatives sidepanel] harvest failed", e);
    return null;
  }
}

async function getConfigStatus() {
  const {
    githubToken = "",
    githubOwner = DEFAULT_GITHUB.owner,
    githubRepo = DEFAULT_GITHUB.repo,
    githubBranch = DEFAULT_GITHUB.branch,
  } = await chrome.storage.local.get([
    "githubToken",
    "githubOwner",
    "githubRepo",
    "githubBranch",
  ]);
  if (githubToken && githubOwner && githubRepo) {
    return {
      ok: true,
      owner: githubOwner,
      repo: githubRepo,
      branch: githubBranch || DEFAULT_GITHUB.branch,
    };
  }
  const missing = [];
  if (!githubToken) missing.push("PAT");
  if (!githubOwner) missing.push("owner");
  if (!githubRepo) missing.push("repo");
  return {
    ok: false,
    missing,
    owner: githubOwner,
    repo: githubRepo,
    branch: githubBranch || DEFAULT_GITHUB.branch,
  };
}

const STATUS_META = {
  "uploaded": { cls: "ok", icon: "✓", label: "uploaded" },
  "already-captured": { cls: "skip", icon: "•", label: "skipped (already captured)" },
  "skipped-exists": { cls: "skip", icon: "•", label: "logged (PDF was already archived)" },
  "error": { cls: "err", icon: "✗", label: "error" },
};

function ensureActivityVisible() {
  for (const el of list.querySelectorAll(".empty")) el.remove();
  clearBtn.hidden = false;
}

function resetActivity() {
  list.innerHTML = `<li class="empty">No uploads yet.</li>`;
  clearBtn.hidden = true;
}

function appendResult(r) {
  ensureActivityVisible();
  const meta = STATUS_META[r.status] || { cls: "skip", icon: "?", label: r.status || "?" };
  const li = document.createElement("li");
  li.className = `ev ${meta.cls}`;
  const detail = r.status === "error" && r.error ? `: ${r.error}` : "";
  li.innerHTML =
    `<span class="ev-icon">${meta.icon}</span>` +
    `<div class="ev-msg">${escapeHtml(meta.label + detail)}` +
    `<span class="ev-file">${escapeHtml(r.filename || r.url || "")}</span></div>`;
  list.appendChild(li);
  list.scrollTop = list.scrollHeight;
}

function appendNote(kind, msg) {
  ensureActivityVisible();
  const meta = STATUS_META[kind] || { cls: kind, icon: kind === "err" ? "!" : "·" };
  const li = document.createElement("li");
  li.className = `ev ${meta.cls}`;
  li.innerHTML =
    `<span class="ev-icon">${meta.icon}</span>` +
    `<div class="ev-msg">${escapeHtml(msg)}</div>`;
  list.appendChild(li);
  list.scrollTop = list.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

clearBtn.addEventListener("click", resetActivity);

function summaryParts(summary) {
  const parts = [];
  if (summary.uploaded) parts.push(`${summary.uploaded} new`);
  if (summary["skipped-exists"]) parts.push(`${summary["skipped-exists"]} logged`);
  if (summary["already-captured"]) parts.push(`${summary["already-captured"]} dupe`);
  if (summary.error) parts.push(`${summary.error} err`);
  return parts.join(", ") || "no changes";
}

function archiveHref(cfg, county = "") {
  const branch = encodeURIComponent(cfg.branch || DEFAULT_GITHUB.branch);
  const suffix = county ? `/archive/${county}` : "/archive";
  return `https://github.com/${cfg.owner}/${cfg.repo}/tree/${branch}${suffix}`;
}

function setArchiveLink(cfg, county = "") {
  if (!cfg.owner || !cfg.repo) return;
  archiveLink.href = archiveHref(cfg, county);
  archiveLink.hidden = false;
}

function setBusy(isNowBusy, cfg, county) {
  busy = isNowBusy;
  uploadBtn.disabled = isNowBusy || !currentState.cfg.ok || currentState.pdfs.length === 0;
  rescanBtn.disabled = isNowBusy;
  setPageActionsDisabled(isNowBusy);
  if (!isNowBusy) {
    setArchiveLink(cfg, county || currentState.county || "");
    if (pendingRefreshAfterBusy) {
      pendingRefreshAfterBusy = false;
      queueRender();
    }
  }
}

async function startUpload(pdfs, county, cfg) {
  setBusy(true, cfg, county);
  uploadBtn.textContent = "Uploading…";
  statusLineEl.textContent = "";
  progressBar.classList.add("on");
  progressFill.style.width = "0%";

  const total = pdfs.length;
  let done = 0;
  const summary = { uploaded: 0, "already-captured": 0, "skipped-exists": 0, error: 0 };

  const port = chrome.runtime.connect({ name: "upload" });
  port.postMessage({ type: "start", county, pdfs });

  return new Promise((resolve) => {
    port.onMessage.addListener((msg) => {
      if (msg.type === "result") {
        appendResult(msg.result);
        summary[msg.result.status] = (summary[msg.result.status] || 0) + 1;
        done += 1;
        const pct = Math.round((done / total) * 100);
        progressFill.style.width = `${pct}%`;
        progressTextEl.textContent = `${done}/${total} (${pct}%)`;
      } else if (msg.type === "done") {
        uploadBtn.textContent = `Done · ${summaryParts(summary)}`;
        progressTextEl.textContent = `${total}/${total} done`;
        setBusy(false, cfg, county);
        port.disconnect();
        resolve();
      } else if (msg.type === "error") {
        appendNote("err", `Fatal: ${msg.error}`);
        uploadBtn.textContent = "Retry";
        setBusy(false, cfg, county);
        port.disconnect();
        resolve();
      }
    });
  });
}

async function startBulkScan(county, cfg, urls = null, label = "Scan") {
  setBusy(true, cfg, county);
  uploadBtn.disabled = true;
  bulkStopBtn.hidden = false;
  bulkStopBtn.disabled = false;
  bulkStatusEl.textContent = urls?.length ? `Fetching ${label}` : "Discovering landing pages…";
  statusLineEl.textContent = "";
  progressBar.classList.add("on");
  progressFill.style.width = "0%";

  let totalPages = 0;
  let pagesDone = 0;
  const summary = { uploaded: 0, "already-captured": 0, "skipped-exists": 0, error: 0 };

  const port = chrome.runtime.connect({ name: "bulk-scan" });
  port.postMessage({ type: "start", county, urls });

  return new Promise((resolve) => {
    const cleanup = () => {
      bulkStopBtn.hidden = true;
      setBusy(false, cfg, county);
      port.disconnect();
      resolve();
    };

    bulkStopBtn.onclick = () => {
      bulkStopBtn.disabled = true;
      bulkStatusEl.textContent = "Stopping after current page…";
      try { port.postMessage({ type: "stop" }); } catch { /* port closed */ }
    };

    port.onMessage.addListener((msg) => {
      if (msg.type === "landings") {
        totalPages = msg.urls.length;
        bulkStatusEl.textContent = totalPages
          ? `Found ${totalPages} page${totalPages === 1 ? "" : "s"}`
          : "No pages to scan";
      } else if (msg.type === "page-start") {
        bulkStatusEl.textContent = `Page ${msg.index + 1}/${msg.total}: ${msg.title}`;
        const pct = Math.round((msg.index / Math.max(1, msg.total)) * 100);
        progressFill.style.width = `${pct}%`;
      } else if (msg.type === "page-harvested") {
        bulkStatusEl.textContent =
          `Page ${msg.index + 1}/${totalPages}: ${msg.title} — ${msg.pdfCount} PDF${msg.pdfCount === 1 ? "" : "s"}`;
        pagesDone = msg.index + 1;
      } else if (msg.type === "page-error") {
        appendNote("err", `${msg.title}: ${msg.error}`);
      } else if (msg.type === "result") {
        appendResult(msg.result);
        summary[msg.result.status] = (summary[msg.result.status] || 0) + 1;
      } else if (msg.type === "done") {
        progressFill.style.width = "100%";
        const tag = msg.reason === "stopped" ? "Stopped" : "Done";
        bulkStatusEl.textContent =
          `${tag} · ${pagesDone}/${totalPages} pages · ${summaryParts(summary)}`;
        cleanup();
      } else if (msg.type === "error") {
        appendNote("err", `Fatal: ${msg.error}`);
        bulkStatusEl.textContent = `Failed: ${msg.error}`;
        cleanup();
      }
    });
  });
}

function renderCountyPages(cfg) {
  countyBlocks.innerHTML = "";
  pageActionButtons.clear();

  for (const [county, pages] of Object.entries(SIDEBAR_PAGES)) {
    const block = document.createElement("section");
    block.className = "county-block";

    const head = document.createElement("div");
    head.className = "county-head";
    head.innerHTML =
      `<h3>${escapeHtml(COUNTY_LABEL[county] || county)}</h3>` +
      `<button class="btn small" type="button" title="Fetch every known landing page for this county">Scan all</button>`;
    const scanBtn = head.querySelector("button");
    scanBtn.dataset.configOk = String(cfg.ok && !!COUNTY_SCAN[county]);
    scanBtn.disabled = !cfg.ok || !COUNTY_SCAN[county];
    scanBtn.addEventListener("click", () => startBulkScan(county, cfg, null, COUNTY_LABEL[county] || county));
    pageActionButtons.add(scanBtn);
    block.appendChild(head);

    const rows = document.createElement("div");
    rows.className = "page-list";
    for (const page of pages) {
      const row = document.createElement("div");
      row.className = "page-row";
      const label = document.createElement("span");
      label.className = "page-label";
      label.textContent = page.label;

      const actions = document.createElement("span");
      actions.className = "page-actions";
      const goBtn = document.createElement("button");
      goBtn.className = "btn icon";
      goBtn.type = "button";
      goBtn.title = `Open ${page.label} in the active tab`;
      goBtn.textContent = "↗";
      goBtn.dataset.configOk = "true";
      goBtn.addEventListener("click", async () => {
        statusLineEl.textContent = `Opening ${page.label}…`;
        await navigateActiveTab(page.url);
      });

      const fetchBtn = document.createElement("button");
      fetchBtn.className = "btn small";
      fetchBtn.type = "button";
      fetchBtn.title = `Fetch and upload PDFs from ${page.label}`;
      fetchBtn.textContent = "Fetch";
      fetchBtn.dataset.configOk = String(cfg.ok);
      fetchBtn.disabled = !cfg.ok;
      fetchBtn.addEventListener("click", () => startBulkScan(county, cfg, [page.url], page.label));

      pageActionButtons.add(goBtn);
      pageActionButtons.add(fetchBtn);
      actions.append(goBtn, fetchBtn);
      row.append(label, actions);
      rows.appendChild(row);
    }
    block.appendChild(rows);
    countyBlocks.appendChild(block);
  }
}

async function render() {
  progressBar.classList.remove("on");
  archiveLink.hidden = true;
  statusLineEl.textContent = "";
  bulkStatusEl.textContent = "";
  progressTextEl.textContent = "";
  uploadBtn.textContent = "Upload";
  uploadBtn.disabled = true;
  rescanBtn.disabled = false;

  const tab = await activeTab();
  const url = tab?.url || "";
  let host = "";
  try { host = url ? new URL(url).hostname : ""; } catch { /* leave blank */ }
  hostEl.textContent = host || "(no tab)";

  const cfg = await getConfigStatus();
  renderCountyPages(cfg);
  if (cfg.ok) {
    setConn("ok", `${cfg.owner}/${cfg.repo}`);
    setArchiveLink(cfg);
  } else {
    setConn("err", `Missing: ${cfg.missing.join(", ")} — open Settings`);
  }

  const county = countyForUrl(url);
  if (!county) {
    setPill(countyEl, "not a supported court page", "warn");
    setPill(countEl, "—", "mute");
    statusLineEl.textContent = "Open a supported court page, or use the Pages list below.";
    return { county: null, pdfs: [], cfg };
  }
  setPill(countyEl, COUNTY_LABEL[county] || county, "ok");

  if (!tab?.id) {
    setPill(countEl, "no active tab", "err");
    statusLineEl.textContent = "Could not read the active tab. Try clicking the court tab, then re-scan.";
    return { county, pdfs: [], cfg };
  }

  const pdfs = await harvestFromTab(tab.id);
  if (pdfs === null) {
    setPill(countEl, "harvest failed", "err");
    statusLineEl.textContent = "Content script did not run. Reload the tab, then re-scan.";
    return { county, pdfs: [], cfg };
  }
  pdfs.sort((a, b) => (a.filename || a.url).localeCompare(b.filename || b.url));

  if (pdfs.length === 0) {
    setPill(countEl, "0 PDFs", "warn");
    statusLineEl.textContent = "No PDF links found in the active tab.";
    setArchiveLink(cfg, county);
    return { county, pdfs: [], cfg };
  }

  setPill(countEl, `${pdfs.length} PDF${pdfs.length === 1 ? "" : "s"}`, "ok");
  statusLineEl.textContent = cfg.ok
    ? `Ready to upload ${pdfs.length}.`
    : "Set GitHub PAT/owner/repo in Settings before uploading.";
  uploadBtn.disabled = !cfg.ok;
  setArchiveLink(cfg, county);
  return { county, pdfs, cfg };
}

let currentState = { county: null, pdfs: [], cfg: { ok: false } };

rescanBtn.addEventListener("click", async () => {
  rescanBtn.disabled = true;
  await refreshPanel();
});

uploadBtn.addEventListener("click", async () => {
  if (!currentState.county || currentState.pdfs.length === 0 || !currentState.cfg.ok) return;
  await startUpload(currentState.pdfs, currentState.county, currentState.cfg);
});

function initStaticBits() {
  const manifest = chrome.runtime.getManifest?.();
  if (manifest?.version) versionEl.textContent = manifest.version;

  chrome.storage.local.get(["githubOwner", "githubRepo"]).then((s) => {
    const owner = s.githubOwner || DEFAULT_GITHUB.owner;
    const repo = s.githubRepo || DEFAULT_GITHUB.repo;
    viewerLink.href = `https://${owner}.github.io/${repo}/`;
  });
}

function queueRender(delayMs = 100) {
  if (busy) {
    pendingRefreshAfterBusy = true;
    return;
  }
  clearTimeout(renderTimer);
  renderTimer = setTimeout(() => {
    refreshPanel().catch(showSidePanelError);
  }, delayMs);
}

async function refreshPanel() {
  if (renderInFlight) {
    renderAgain = true;
    return;
  }
  renderInFlight = true;
  try {
    currentState = await render();
  } finally {
    renderInFlight = false;
    if (renderAgain) {
      renderAgain = false;
      queueRender(0);
    }
  }
}

function showSidePanelError(e) {
  console.error("[tentatives sidepanel] fatal", e);
  statusLineEl.textContent = `Side panel error: ${e.message || e}`;
  setConn("err", "Side panel error");
}

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (!Object.keys(changes).some((key) => CONFIG_KEYS.has(key))) return;
  queueRender(0);
});

chrome.tabs.onActivated.addListener(() => queueRender(0));

chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (!tab?.active) return;
  if (changeInfo.status === "complete" || changeInfo.url) queueRender(250);
});

chrome.windows?.onFocusChanged?.addListener(() => queueRender(0));

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg?.type !== "page-loaded") return;
  if (sender?.tab?.active) queueRender(0);
});

(async () => {
  console.log("[tentatives sidepanel] opened");
  initStaticBits();
  await refreshPanel();
})().catch(showSidePanelError);
