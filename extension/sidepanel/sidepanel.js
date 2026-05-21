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
const activeWaybackBtn = $("active-wayback");
const bulkStopBtn = $("bulk-stop");
const scanSelectedBtn = $("scan-selected");
const shellSelectedBtn = $("shell-selected");
const selectAllCourtsEl = $("select-all-courts");
const bulkPauseBtn = document.createElement("button");
const bulkControlsEl = document.createElement("span");
const clearBtn = $("clear-activity");
const countyBlocks = $("county-blocks");

const list = $("results");
const progressBar = $("progress-bar");
const progressFill = $("progress-fill");

const archiveLink = $("archive-link");
const viewerLink = $("open-viewer");
const versionEl = $("ext-version");

const pageActionButtons = new Set();
const countySelectionInputs = new Set();
const selectedCountyState = new Map();
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

bulkPauseBtn.className = "btn small";
bulkPauseBtn.type = "button";
bulkPauseBtn.textContent = "Pause scan";
bulkPauseBtn.title = "Pause the current bulk scan";
bulkControlsEl.className = "row";
bulkControlsEl.hidden = true;
bulkStopBtn.parentElement.insertBefore(bulkControlsEl, bulkStopBtn);
bulkControlsEl.append(bulkPauseBtn, bulkStopBtn);

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
  for (const input of countySelectionInputs) {
    input.disabled = disabled;
  }
  selectAllCourtsEl.disabled = disabled;
  scanSelectedBtn.disabled = disabled
    || !currentState.cfg.ok
    || selectedScanCounties().length === 0;
  shellSelectedBtn.disabled = scanSelectedBtn.disabled;
}

function isCountySelected(county) {
  return selectedCountyState.get(county) !== false;
}

function selectedScanCounties() {
  return Object.keys(SIDEBAR_PAGES).filter((county) =>
    isCountySelected(county) && !!COUNTY_SCAN[county]
  );
}

function syncSelectionControls(cfg = currentState.cfg) {
  const allCounties = Object.keys(SIDEBAR_PAGES).filter((county) => !!COUNTY_SCAN[county]);
  const selected = selectedScanCounties();
  selectAllCourtsEl.checked = allCounties.length > 0 && selected.length === allCounties.length;
  selectAllCourtsEl.indeterminate = selected.length > 0 && selected.length < allCounties.length;
  scanSelectedBtn.disabled = busy || !cfg.ok || selected.length === 0;
  shellSelectedBtn.disabled = scanSelectedBtn.disabled;
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

function waybackUrl(url) {
  const target = new URL(url);
  target.hash = "";
  return `https://web.archive.org/web/*/${target.href}`;
}

function canOpenWayback(url) {
  try {
    const protocol = new URL(url).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

async function navigateActiveTabToWayback(url) {
  if (!canOpenWayback(url)) return;
  await navigateActiveTab(waybackUrl(url));
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
  "page-captured": { cls: "ok", icon: "✓", label: "captured page snapshot" },
  "page-logged": { cls: "skip", icon: "•", label: "logged page snapshot" },
  "page-unchanged": { cls: "skip", icon: "•", label: "skipped unchanged page" },
  "layout-captured": { cls: "ok", icon: "✓", label: "captured page layout" },
  "layout-logged": { cls: "skip", icon: "•", label: "logged page layout" },
  "layout-unchanged": { cls: "skip", icon: "•", label: "skipped unchanged layout" },
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

selectAllCourtsEl.addEventListener("change", () => {
  const checked = selectAllCourtsEl.checked;
  for (const county of Object.keys(SIDEBAR_PAGES)) {
    selectedCountyState.set(county, checked);
  }
  for (const input of countySelectionInputs) {
    input.checked = checked;
  }
  syncSelectionControls();
});

scanSelectedBtn.addEventListener("click", async () => {
  if (busy || !currentState.cfg.ok) return;
  await startSelectedScan(currentState.cfg);
});

shellSelectedBtn.addEventListener("click", async () => {
  if (busy || !currentState.cfg.ok) return;
  await startShellScan(currentState.cfg);
});

function summaryParts(summary) {
  const parts = [];
  if (summary.uploaded) parts.push(`${summary.uploaded} new`);
  if (summary["skipped-exists"]) parts.push(`${summary["skipped-exists"]} logged`);
  if (summary["already-captured"]) parts.push(`${summary["already-captured"]} dupe`);
  if (summary["page-captured"]) parts.push(`${summary["page-captured"]} pages`);
  if (summary["page-logged"]) parts.push(`${summary["page-logged"]} page logs`);
  if (summary["page-unchanged"]) parts.push(`${summary["page-unchanged"]} unchanged pages`);
  if (summary["layout-captured"]) parts.push(`${summary["layout-captured"]} layouts`);
  if (summary["layout-logged"]) parts.push(`${summary["layout-logged"]} layout logs`);
  if (summary["layout-unchanged"]) parts.push(`${summary["layout-unchanged"]} unchanged layouts`);
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
  activeWaybackBtn.disabled = isNowBusy || !canOpenWayback(currentState.url || "");
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
  bulkControlsEl.hidden = false;
  bulkPauseBtn.hidden = false;
  bulkPauseBtn.disabled = false;
  bulkPauseBtn.textContent = "Pause scan";
  bulkPauseBtn.title = "Pause the current bulk scan";
  bulkStopBtn.hidden = false;
  bulkStopBtn.disabled = false;
  bulkStatusEl.textContent = urls?.length ? `Fetching ${label}` : "Discovering landing pages…";
  statusLineEl.textContent = "";
  progressBar.classList.add("on");
  progressFill.style.width = "0%";

  let totalPages = 0;
  let pagesDone = 0;
  let bulkPaused = false;
  const summary = { uploaded: 0, "already-captured": 0, "skipped-exists": 0, error: 0 };

  const port = chrome.runtime.connect({ name: "bulk-scan" });
  port.postMessage({ type: "start", county, urls });

  return new Promise((resolve) => {
    const cleanup = (reason = "completed") => {
      bulkControlsEl.hidden = true;
      bulkPauseBtn.disabled = true;
      bulkStopBtn.hidden = true;
      bulkPauseBtn.onclick = null;
      bulkStopBtn.onclick = null;
      setBusy(false, cfg, county);
      try { port.disconnect(); } catch { /* already closed */ }
      resolve(reason);
    };

    bulkPauseBtn.onclick = () => {
      const type = bulkPaused ? "resume" : "pause";
      bulkPauseBtn.disabled = true;
      bulkStatusEl.textContent = bulkPaused ? "Resuming scan..." : "Pausing scan...";
      try { port.postMessage({ type }); } catch { /* port closed */ }
    };

    bulkStopBtn.onclick = () => {
      bulkStopBtn.disabled = true;
      bulkPauseBtn.disabled = true;
      try { port.postMessage({ type: "stop" }); } catch { /* port closed */ }
      bulkStatusEl.textContent = "Stopping scan...";
    };

    port.onMessage.addListener((msg) => {
      if (msg.type === "control-state") {
        bulkPaused = !!msg.paused;
        bulkPauseBtn.disabled = !!msg.stopped;
        bulkPauseBtn.textContent = bulkPaused ? "Resume scan" : "Pause scan";
        bulkPauseBtn.title = bulkPaused ? "Resume the current bulk scan" : "Pause the current bulk scan";
        if (msg.stopped) {
          bulkStatusEl.textContent = "Stopping scan...";
        } else if (bulkPaused) {
          bulkStatusEl.textContent = "Paused - resume when ready";
        }
      } else if (msg.type === "landings") {
        totalPages = msg.urls.length;
        bulkStatusEl.textContent = totalPages
          ? `Found ${totalPages} page${totalPages === 1 ? "" : "s"}`
          : "No pages to scan";
      } else if (msg.type === "page-start") {
        const retryLabel = msg.attempt > 1
          ? ` (retry ${msg.attempt - 1}/${Math.max(1, msg.maxAttempts - 1)})`
          : "";
        bulkStatusEl.textContent = `Page ${msg.index + 1}/${msg.total}${retryLabel}: ${msg.title}`;
        const pct = Math.round((msg.index / Math.max(1, msg.total)) * 100);
        progressFill.style.width = `${pct}%`;
      } else if (msg.type === "page-harvested") {
        const pagePart = msg.pageSnapshotCount
          ? `, ${msg.pageSnapshotCount} page snapshot${msg.pageSnapshotCount === 1 ? "" : "s"}`
          : "";
        const layoutPart = msg.layoutCount
          ? `, ${msg.layoutCount} layout${msg.layoutCount === 1 ? "" : "s"}`
          : "";
        bulkStatusEl.textContent =
          `Page ${msg.index + 1}/${totalPages}: ${msg.title} — ${msg.pdfCount} PDF${msg.pdfCount === 1 ? "" : "s"}${pagePart}${layoutPart}`;
        pagesDone = msg.index + 1;
      } else if (msg.type === "page-retry") {
        const text = `Retry ${msg.retry}/${msg.maxRetries}: ${msg.title} (${msg.error})`;
        bulkStatusEl.textContent = text;
        appendNote("warn", text);
      } else if (msg.type === "page-error") {
        pagesDone = Math.max(pagesDone, msg.index + 1);
        appendNote("err", `${msg.title}: ${msg.error}`);
      } else if (msg.type === "result") {
        appendResult(msg.result);
        summary[msg.result.status] = (summary[msg.result.status] || 0) + 1;
      } else if (msg.type === "done") {
        progressFill.style.width = "100%";
        const tag = msg.reason === "stopped" ? "Stopped" : "Done";
        bulkStatusEl.textContent =
          `${tag} · ${pagesDone}/${totalPages} pages · ${summaryParts(summary)}`;
        cleanup(msg.reason || "completed");
      } else if (msg.type === "error") {
        appendNote("err", `Fatal: ${msg.error}`);
        bulkStatusEl.textContent = `Failed: ${msg.error}`;
        cleanup("error");
      }
    });
  });
}

async function startShellScan(cfg) {
  const counties = selectedScanCounties();
  if (!cfg.ok || counties.length === 0) return "no-counties";
  setBusy(true, cfg, "");
  uploadBtn.disabled = true;
  bulkControlsEl.hidden = false;
  bulkPauseBtn.hidden = false;
  bulkPauseBtn.disabled = false;
  bulkPauseBtn.textContent = "Pause shell";
  bulkPauseBtn.title = "Pause the parallel browser scan";
  bulkStopBtn.hidden = false;
  bulkStopBtn.disabled = false;
  bulkStatusEl.textContent = `Starting ${counties.length} selected court${counties.length === 1 ? "" : "s"}...`;
  statusLineEl.textContent = "";
  progressBar.classList.add("on");
  progressFill.style.width = "0%";
  appendNote("warn", `Shell scan: ${counties.length} selected court${counties.length === 1 ? "" : "s"}.`);

  let totalCounties = counties.length;
  let doneCounties = 0;
  let totalPages = 0;
  let pagesDone = 0;
  let shellPaused = false;
  const summary = { uploaded: 0, "already-captured": 0, "skipped-exists": 0, error: 0 };

  const updateProgress = () => {
    const pct = totalPages > 0
      ? Math.round((pagesDone / Math.max(1, totalPages)) * 100)
      : Math.round((doneCounties / Math.max(1, totalCounties)) * 100);
    progressFill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    progressTextEl.textContent = totalPages > 0
      ? `${pagesDone}/${totalPages} pages`
      : `${doneCounties}/${totalCounties} courts`;
  };

  const port = chrome.runtime.connect({ name: "shell-scan" });
  port.postMessage({ type: "start", counties });

  return new Promise((resolve) => {
    const cleanup = (reason = "completed") => {
      bulkControlsEl.hidden = true;
      bulkPauseBtn.disabled = true;
      bulkStopBtn.hidden = true;
      bulkPauseBtn.onclick = null;
      bulkStopBtn.onclick = null;
      setBusy(false, cfg, "");
      try { port.disconnect(); } catch { /* already closed */ }
      resolve(reason);
    };

    bulkPauseBtn.onclick = () => {
      const type = shellPaused ? "resume" : "pause";
      bulkPauseBtn.disabled = true;
      bulkStatusEl.textContent = shellPaused ? "Resuming shell scan..." : "Pausing shell scan...";
      try { port.postMessage({ type }); } catch { /* port closed */ }
    };

    bulkStopBtn.onclick = () => {
      bulkStopBtn.disabled = true;
      bulkPauseBtn.disabled = true;
      try { port.postMessage({ type: "stop" }); } catch { /* port closed */ }
      bulkStatusEl.textContent = "Stopping shell scan...";
    };

    port.onMessage.addListener((msg) => {
      if (msg.type === "queue") {
        totalCounties = msg.counties.length;
        bulkStatusEl.textContent =
          `Shell scan: ${totalCounties} court${totalCounties === 1 ? "" : "s"}, ${msg.concurrency} tab${msg.concurrency === 1 ? "" : "s"}`;
        updateProgress();
      } else if (msg.type === "control-state") {
        shellPaused = !!msg.paused;
        bulkPauseBtn.disabled = !!msg.stopped;
        bulkPauseBtn.textContent = shellPaused ? "Resume shell" : "Pause shell";
        bulkPauseBtn.title = shellPaused ? "Resume the parallel browser scan" : "Pause the parallel browser scan";
        if (msg.stopped) {
          bulkStatusEl.textContent = "Stopping shell scan...";
        } else if (shellPaused && msg.human) {
          bulkStatusEl.textContent = `Paused for human check: ${msg.reason || "review tab"}`;
        } else if (shellPaused) {
          bulkStatusEl.textContent = "Shell paused - resume when ready";
        }
      } else if (msg.type === "county-start") {
        const label = COUNTY_LABEL[msg.county] || msg.county;
        bulkStatusEl.textContent = `Tab ${msg.workerIndex + 1}: ${label} ${msg.phase || "starting"}`;
      } else if (msg.type === "county-landings") {
        const label = COUNTY_LABEL[msg.county] || msg.county;
        totalPages += msg.urls.length;
        bulkStatusEl.textContent = `${label}: ${msg.urls.length} page${msg.urls.length === 1 ? "" : "s"}`;
        updateProgress();
      } else if (msg.type === "page-start") {
        const label = COUNTY_LABEL[msg.county] || msg.county;
        const retryLabel = msg.attempt > 1
          ? ` retry ${msg.attempt - 1}/${Math.max(1, msg.maxAttempts - 1)}`
          : "";
        bulkStatusEl.textContent = `Tab ${msg.workerIndex + 1}: ${label} ${msg.index + 1}/${msg.total}${retryLabel} - ${msg.title}`;
      } else if (msg.type === "page-harvested") {
        const label = COUNTY_LABEL[msg.county] || msg.county;
        pagesDone += 1;
        const pagePart = msg.pageSnapshotCount
          ? `, ${msg.pageSnapshotCount} page snapshot${msg.pageSnapshotCount === 1 ? "" : "s"}`
          : "";
        const layoutPart = msg.layoutCount
          ? `, ${msg.layoutCount} layout${msg.layoutCount === 1 ? "" : "s"}`
          : "";
        bulkStatusEl.textContent =
          `${label}: ${msg.title} - ${msg.pdfCount} PDF${msg.pdfCount === 1 ? "" : "s"}${pagePart}${layoutPart}`;
        updateProgress();
      } else if (msg.type === "human-pause") {
        const label = COUNTY_LABEL[msg.county] || msg.county;
        appendNote("warn", `${label}: human check (${msg.reason || "review tab"})`);
        bulkStatusEl.textContent = `${label}: resolve the open tab, then resume`;
      } else if (msg.type === "page-retry") {
        const label = COUNTY_LABEL[msg.county] || msg.county;
        const text = `${label}: retry ${msg.retry}/${msg.maxRetries} ${msg.title} (${msg.error})`;
        bulkStatusEl.textContent = text;
        appendNote("warn", text);
      } else if (msg.type === "page-error") {
        pagesDone += 1;
        const label = COUNTY_LABEL[msg.county] || msg.county;
        appendNote("err", `${label} ${msg.title}: ${msg.error}`);
        updateProgress();
      } else if (msg.type === "county-error") {
        doneCounties = Math.max(doneCounties, msg.completedCounties || doneCounties + 1);
        const label = COUNTY_LABEL[msg.county] || msg.county;
        appendNote("err", `${label}: ${msg.error}`);
        updateProgress();
      } else if (msg.type === "county-done") {
        doneCounties = Math.max(doneCounties, msg.completedCounties || doneCounties + 1);
        const label = COUNTY_LABEL[msg.county] || msg.county;
        bulkStatusEl.textContent = `${label}: done (${doneCounties}/${totalCounties} courts)`;
        updateProgress();
      } else if (msg.type === "result") {
        appendResult(msg.result);
        summary[msg.result.status] = (summary[msg.result.status] || 0) + 1;
      } else if (msg.type === "done") {
        progressFill.style.width = "100%";
        const tag = msg.reason === "stopped" ? "Stopped" : "Done";
        bulkStatusEl.textContent =
          `${tag} shell scan - ${doneCounties}/${totalCounties} courts, ${pagesDone}/${totalPages || pagesDone} pages - ${summaryParts(summary)}`;
        cleanup(msg.reason || "completed");
      } else if (msg.type === "error") {
        appendNote("err", `Fatal: ${msg.error}`);
        bulkStatusEl.textContent = `Shell failed: ${msg.error}`;
        cleanup("error");
      }
    });
  });
}

async function startSelectedScan(cfg) {
  const counties = selectedScanCounties();
  if (!cfg.ok || counties.length === 0) return;
  appendNote("warn", `Scanning ${counties.length} selected court${counties.length === 1 ? "" : "s"}.`);
  for (let i = 0; i < counties.length; i++) {
    const county = counties[i];
    const label = COUNTY_LABEL[county] || county;
    bulkStatusEl.textContent = `Selected ${i + 1}/${counties.length}: ${label}`;
    const reason = await startBulkScan(county, cfg, null, label);
    if (reason === "stopped" || reason === "error") break;
  }
}

function renderCountyPages(cfg) {
  countyBlocks.innerHTML = "";
  pageActionButtons.clear();
  countySelectionInputs.clear();

  for (const [county, pages] of Object.entries(SIDEBAR_PAGES)) {
    const block = document.createElement("section");
    block.className = "county-block";

    const head = document.createElement("div");
    head.className = "county-head";
    const selectLabel = document.createElement("label");
    selectLabel.className = "county-select";
    const selectInput = document.createElement("input");
    selectInput.type = "checkbox";
    selectInput.checked = isCountySelected(county);
    selectInput.disabled = busy;
    selectInput.addEventListener("change", () => {
      selectedCountyState.set(county, selectInput.checked);
      syncSelectionControls(cfg);
    });
    const countyName = document.createElement("span");
    countyName.textContent = COUNTY_LABEL[county] || county;
    selectLabel.append(selectInput, countyName);
    countySelectionInputs.add(selectInput);

    const scanBtn = document.createElement("button");
    scanBtn.className = "btn small";
    scanBtn.type = "button";
    scanBtn.title = "Fetch every known landing page for this county";
    scanBtn.textContent = "Scan all";
    scanBtn.dataset.configOk = String(cfg.ok && !!COUNTY_SCAN[county]);
    scanBtn.disabled = !cfg.ok || !COUNTY_SCAN[county];
    scanBtn.addEventListener("click", () => startBulkScan(county, cfg, null, COUNTY_LABEL[county] || county));
    pageActionButtons.add(scanBtn);
    head.append(selectLabel, scanBtn);
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

      const waybackBtn = document.createElement("button");
      waybackBtn.className = "btn small";
      waybackBtn.type = "button";
      waybackBtn.title = `Open Wayback snapshots for ${page.label}`;
      waybackBtn.textContent = "Wayback";
      waybackBtn.dataset.configOk = "true";
      waybackBtn.addEventListener("click", async () => {
        statusLineEl.textContent = `Opening Wayback for ${page.label}...`;
        await navigateActiveTabToWayback(page.url);
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
      pageActionButtons.add(waybackBtn);
      pageActionButtons.add(fetchBtn);
      actions.append(goBtn, waybackBtn, fetchBtn);
      row.append(label, actions);
      rows.appendChild(row);
    }
    block.appendChild(rows);
    countyBlocks.appendChild(block);
  }
  syncSelectionControls(cfg);
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
  activeWaybackBtn.disabled = true;

  const tab = await activeTab();
  const url = tab?.url || "";
  activeWaybackBtn.disabled = !canOpenWayback(url);
  activeWaybackBtn.title = canOpenWayback(url)
    ? "Open Wayback snapshots for the active tab"
    : "Open an http(s) page to use Wayback";
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
    return { county: null, pdfs: [], cfg, url };
  }
  setPill(countyEl, COUNTY_LABEL[county] || county, "ok");

  if (!tab?.id) {
    setPill(countEl, "no active tab", "err");
    statusLineEl.textContent = "Could not read the active tab. Try clicking the court tab, then re-scan.";
    return { county, pdfs: [], cfg, url };
  }

  const pdfs = await harvestFromTab(tab.id);
  if (pdfs === null) {
    setPill(countEl, "harvest failed", "err");
    statusLineEl.textContent = "Content script did not run. Reload the tab, then re-scan.";
    return { county, pdfs: [], cfg, url };
  }
  pdfs.sort((a, b) => (a.filename || a.url).localeCompare(b.filename || b.url));

  if (pdfs.length === 0) {
    setPill(countEl, "0 PDFs", "warn");
    statusLineEl.textContent = "No PDF links found in the active tab.";
    setArchiveLink(cfg, county);
    return { county, pdfs: [], cfg, url };
  }

  setPill(countEl, `${pdfs.length} PDF${pdfs.length === 1 ? "" : "s"}`, "ok");
  statusLineEl.textContent = cfg.ok
    ? `Ready to upload ${pdfs.length}.`
    : "Set GitHub PAT/owner/repo in Settings before uploading.";
  uploadBtn.disabled = !cfg.ok;
  setArchiveLink(cfg, county);
  return { county, pdfs, cfg, url };
}

let currentState = { county: null, pdfs: [], cfg: { ok: false }, url: "" };

rescanBtn.addEventListener("click", async () => {
  rescanBtn.disabled = true;
  await refreshPanel();
});

activeWaybackBtn.addEventListener("click", async () => {
  const tab = await activeTab();
  const url = tab?.url || currentState.url || "";
  await navigateActiveTabToWayback(url);
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
