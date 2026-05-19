// Popup: shows live diagnostic state for the active tab, plus Upload and
// Scan-all-depts actions. Streams results from the background service worker
// into the activity log.

const $ = (id) => document.getElementById(id);

const hostEl    = $("d-host");
const countyEl  = $("d-county");
const countEl   = $("d-pdfcount");
const connDot   = $("conn-dot");
const connText  = $("conn-text");

const statusLineEl = $("status-line");
const progressTextEl = $("progress-text");
const bulkStatusEl = $("bulk-status");

const uploadBtn = $("upload");
const rescanBtn = $("rescan");
const bulkBtn   = $("bulk-scan");
const bulkStopBtn = $("bulk-stop");
const clearBtn  = $("clear-activity");

const list = $("results");

const progressBar = $("progress-bar");
const progressFill = $("progress-fill");

const archiveLink = $("archive-link");
const viewerLink  = $("open-viewer");
const versionEl   = $("ext-version");

$("open-options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});
$("reload-page").addEventListener("click", async (e) => {
  e.preventDefault();
  const tab = await activeTab();
  if (tab) chrome.tabs.reload(tab.id);
});

const HOST_TO_COUNTY = {
  "eldorado.courts.ca.gov": "el-dorado",
  "www.eldorado.courts.ca.gov": "el-dorado",
  "placer.courts.ca.gov": "placer",
  "www.placer.courts.ca.gov": "placer",
  "contracosta.courts.ca.gov": "contra-costa",
  "www.contracosta.courts.ca.gov": "contra-costa",
  "cc-courts.org": "contra-costa",
  "www.cc-courts.org": "contra-costa",
  "retired.cc-courts.org": "contra-costa",
};

const COUNTY_LABEL = {
  "el-dorado": "El Dorado",
  "placer": "Placer",
  "contra-costa": "Contra Costa",
};

// Counties whose bulk scan is wired up in the background service worker.
// Keep in sync with COUNTY_SCAN in background.js.
const BULK_SUPPORTED = new Set(["el-dorado", "placer", "contra-costa"]);

function setPill(el, text, kind = "mute") {
  el.innerHTML = `<span class="pill ${kind}">${text}</span>`;
}

function setConn(kind, text) {
  connDot.className = `dot ${kind}`;
  connText.textContent = text;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function harvestFromTab(tabId) {
  try {
    // allFrames: true so a Contra Costa iframe (cc-courts.org inside the
    // contracosta.courts.ca.gov shell) contributes its harvested PDFs too.
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
    console.error("[tentatives popup] harvest failed", e);
    return null;
  }
}

async function getConfigStatus() {
  const { githubToken = "", githubOwner = "", githubRepo = "" } =
    await chrome.storage.local.get(["githubToken", "githubOwner", "githubRepo"]);
  if (githubToken && githubOwner && githubRepo) {
    return { ok: true, owner: githubOwner, repo: githubRepo };
  }
  const missing = [];
  if (!githubToken) missing.push("PAT");
  if (!githubOwner) missing.push("owner");
  if (!githubRepo) missing.push("repo");
  return { ok: false, missing };
}

const STATUS_META = {
  "uploaded":          { cls: "ok",   icon: "✓", label: "uploaded" },
  "already-captured":  { cls: "skip", icon: "•", label: "skipped (already captured)" },
  "skipped-exists":    { cls: "skip", icon: "•", label: "logged (PDF was already archived)" },
  "error":             { cls: "err",  icon: "✗", label: "error" },
};

function ensureActivityVisible() {
  // Drop any "empty" placeholder before appending real activity.
  for (const el of list.querySelectorAll(".empty")) el.remove();
  clearBtn.hidden = false;
}

function resetActivity() {
  list.innerHTML = `<li class="empty">No uploads yet on this page.</li>`;
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
  const meta = STATUS_META[kind] || { cls: kind, icon: kind === "err" ? "!" : "·", label: "" };
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
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

clearBtn.addEventListener("click", resetActivity);

function summaryParts(summary) {
  const parts = [];
  if (summary.uploaded)            parts.push(`${summary.uploaded} new`);
  if (summary["skipped-exists"])   parts.push(`${summary["skipped-exists"]} logged`);
  if (summary["already-captured"]) parts.push(`${summary["already-captured"]} dupe`);
  if (summary.error)               parts.push(`${summary.error} err`);
  return parts.join(", ") || "no changes";
}

async function startUpload(pdfs, county, cfg) {
  uploadBtn.disabled = true;
  rescanBtn.disabled = true;
  bulkBtn.disabled = true;
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
        rescanBtn.disabled = false;
        bulkBtn.disabled = !(cfg.ok && BULK_SUPPORTED.has(county));
        port.disconnect();
        if (cfg.ok) {
          archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive/${county}`;
          archiveLink.hidden = false;
        }
        resolve();
      } else if (msg.type === "error") {
        appendNote("err", `Fatal: ${msg.error}`);
        uploadBtn.textContent = "Retry";
        uploadBtn.disabled = false;
        rescanBtn.disabled = false;
        bulkBtn.disabled = !(cfg.ok && BULK_SUPPORTED.has(county));
        port.disconnect();
        resolve();
      }
    });
  });
}

async function startBulkScan(county, cfg) {
  uploadBtn.disabled = true;
  rescanBtn.disabled = true;
  bulkBtn.disabled = true;
  bulkBtn.textContent = "Scanning…";
  bulkStopBtn.hidden = false;
  bulkStopBtn.disabled = false;
  bulkStatusEl.textContent = "Discovering landing pages…";
  statusLineEl.textContent = "";
  progressBar.classList.add("on");
  progressFill.style.width = "0%";

  let totalPages = 0;
  let pagesDone = 0;
  const summary = { uploaded: 0, "already-captured": 0, "skipped-exists": 0, error: 0 };

  const port = chrome.runtime.connect({ name: "bulk-scan" });
  port.postMessage({ type: "start", county });

  return new Promise((resolve) => {
    const cleanup = () => {
      bulkStopBtn.hidden = true;
      bulkBtn.textContent = "Scan all depts";
      bulkBtn.disabled = !(cfg.ok && BULK_SUPPORTED.has(county));
      rescanBtn.disabled = false;
      uploadBtn.disabled = currentState.pdfs.length === 0 || !cfg.ok;
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
        bulkStatusEl.textContent = `Page ${msg.index + 1}/${totalPages}: ${msg.title} — ${msg.pdfCount} PDF${msg.pdfCount === 1 ? "" : "s"}`;
        pagesDone = msg.index + 1;
      } else if (msg.type === "page-error") {
        appendNote("err", `${msg.title}: ${msg.error}`);
      } else if (msg.type === "result") {
        appendResult(msg.result);
        summary[msg.result.status] = (summary[msg.result.status] || 0) + 1;
      } else if (msg.type === "done") {
        progressFill.style.width = "100%";
        const tag = msg.reason === "stopped" ? "Stopped" : "Done";
        bulkStatusEl.textContent = `${tag} · ${pagesDone}/${totalPages} pages · ${summaryParts(summary)}`;
        if (cfg.ok) {
          archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive/${county}`;
          archiveLink.hidden = false;
        }
        cleanup();
      } else if (msg.type === "error") {
        appendNote("err", `Fatal: ${msg.error}`);
        bulkStatusEl.textContent = `Failed: ${msg.error}`;
        cleanup();
      }
    });
  });
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
  bulkBtn.disabled = true;
  bulkBtn.textContent = "Scan all depts";

  const tab = await activeTab();
  const url = tab?.url || "";
  let host = "";
  try { host = url ? new URL(url).hostname : ""; } catch { /* leave blank */ }
  hostEl.textContent = host || "(no tab)";

  const cfg = await getConfigStatus();
  if (cfg.ok) {
    setConn("ok", `${cfg.owner}/${cfg.repo}`);
  } else {
    setConn("err", `Missing: ${cfg.missing.join(", ")} — open Settings`);
  }

  const county = HOST_TO_COUNTY[host];
  if (!county) {
    setPill(countyEl, "not a supported court page", "warn");
    setPill(countEl, "—", "mute");
    statusLineEl.textContent = "Open an EDC, Placer, or Contra Costa tentative-ruling page.";
    if (cfg.ok) {
      archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive`;
      archiveLink.hidden = false;
    }
    return { county: null, pdfs: [], cfg };
  }
  setPill(countyEl, COUNTY_LABEL[county] || county, "ok");
  bulkBtn.disabled = !(cfg.ok && BULK_SUPPORTED.has(county));

  const pdfs = await harvestFromTab(tab.id);
  if (pdfs === null) {
    setPill(countEl, "harvest failed", "err");
    statusLineEl.textContent = "Content script didn't run — try Reload page.";
    return { county, pdfs: [], cfg };
  }
  pdfs.sort((a, b) => (a.filename || a.url).localeCompare(b.filename || b.url));

  if (pdfs.length === 0) {
    setPill(countEl, "0 PDFs", "warn");
    statusLineEl.textContent = "No PDF links on this page. Try a dept landing page directly.";
    if (cfg.ok) {
      archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive/${county}`;
      archiveLink.hidden = false;
    }
    return { county, pdfs: [], cfg };
  }

  setPill(countEl, `${pdfs.length} PDF${pdfs.length === 1 ? "" : "s"}`, "ok");
  statusLineEl.textContent = cfg.ok
    ? `Ready to upload ${pdfs.length}.`
    : "Set GitHub PAT/owner/repo in Settings before uploading.";
  uploadBtn.disabled = !cfg.ok;
  if (cfg.ok) {
    archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive/${county}`;
    archiveLink.hidden = false;
  }
  return { county, pdfs, cfg };
}

let currentState = { county: null, pdfs: [], cfg: { ok: false } };

rescanBtn.addEventListener("click", async () => {
  rescanBtn.disabled = true;
  currentState = await render();
});

uploadBtn.addEventListener("click", async () => {
  if (!currentState.county || currentState.pdfs.length === 0 || !currentState.cfg.ok) return;
  await startUpload(currentState.pdfs, currentState.county, currentState.cfg);
});

bulkBtn.addEventListener("click", async () => {
  if (!currentState.county || !currentState.cfg.ok) return;
  if (!BULK_SUPPORTED.has(currentState.county)) return;
  await startBulkScan(currentState.county, currentState.cfg);
});

function initStaticBits() {
  const manifest = chrome.runtime.getManifest?.();
  if (manifest?.version) versionEl.textContent = manifest.version;

  // Site viewer link: prefer user's configured owner/repo, fall back to a
  // generic GitHub Pages search hint.
  chrome.storage.local.get(["githubOwner", "githubRepo"]).then((s) => {
    if (s.githubOwner && s.githubRepo) {
      viewerLink.href = `https://${s.githubOwner}.github.io/${s.githubRepo}/`;
    } else {
      viewerLink.href = "https://aimesy.github.io/tentatives/";
    }
  });
}

(async () => {
  console.log("[tentatives popup] opened");
  initStaticBits();
  currentState = await render();
})().catch((e) => {
  console.error("[tentatives popup] fatal", e);
  statusLineEl.textContent = `Popup error: ${e.message || e}`;
  setConn("err", "Popup error");
});
