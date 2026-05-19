// Popup: shows live diagnostic state for the active tab, plus the Upload action.

const $ = (id) => document.getElementById(id);
const hostEl = $("d-host");
const countyEl = $("d-county");
const countEl = $("d-pdfcount");
const cfgEl = $("d-config");
const statusEl = $("status");
const btn = $("upload");
const rescanBtn = $("rescan");
const list = $("results");
const progressBar = $("progress-bar");
const progressFill = $("progress-fill");
const archiveLink = $("archive-link");
const bulkBtn = $("bulk-scan");
const bulkStopBtn = $("bulk-stop");
const bulkStatusEl = $("bulk-status");

$("opts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});
$("reload").addEventListener("click", async (e) => {
  e.preventDefault();
  const tab = await activeTab();
  if (tab) chrome.tabs.reload(tab.id);
});

const HOST_TO_COUNTY = {
  "eldorado.courts.ca.gov": "el-dorado",
  "www.eldorado.courts.ca.gov": "el-dorado",
  "placer.courts.ca.gov": "placer",
  "www.placer.courts.ca.gov": "placer",
};

// Counties whose bulk scan is wired up in the background service worker.
// Keep in sync with COUNTY_SCAN in background.js.
const BULK_SUPPORTED = new Set(["el-dorado", "placer"]);

function setPill(el, text, kind = "warn") {
  el.innerHTML = `<span class="pill pill-${kind}">${text}</span>`;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function harvestFromTab(tabId) {
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => window.__tentatives_pdfs || [],
    });
    return res?.result || [];
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

function statusLabel(status) {
  switch (status) {
    case "uploaded": return { cls: "status-ok", label: "✓ uploaded" };
    case "already-captured": return { cls: "status-skip", label: "• skipped (already captured)" };
    case "skipped-exists": return { cls: "status-skip", label: "• logged (PDF was already archived)" };
    case "error": return { cls: "status-err", label: "✗ error" };
    default: return { cls: "status-skip", label: status || "?" };
  }
}

function appendResult(r) {
  const li = document.createElement("li");
  const { cls, label } = statusLabel(r.status);
  li.className = cls;
  const detail = r.status === "error" ? `: ${r.error}` : "";
  li.textContent = `${label}${detail} — ${r.filename || r.url}`;
  list.appendChild(li);
  list.scrollTop = list.scrollHeight;
}

async function startUpload(pdfs, county, cfg) {
  btn.disabled = true;
  rescanBtn.disabled = true;
  btn.textContent = "Uploading…";
  statusEl.textContent = "";
  list.innerHTML = "";
  progressBar.classList.add("on");
  progressFill.style.width = "0%";

  const total = pdfs.length;
  let done = 0;
  const summary = { uploaded: 0, "already-captured": 0, "skipped-exists": 0, error: 0 };

  // Open a long-lived port to receive progress events.
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
        statusEl.textContent = `Uploading ${done} of ${total} (${pct}%)…`;
      } else if (msg.type === "done") {
        const parts = [];
        if (summary.uploaded) parts.push(`${summary.uploaded} new`);
        if (summary["skipped-exists"]) parts.push(`${summary["skipped-exists"]} logged`);
        if (summary["already-captured"]) parts.push(`${summary["already-captured"]} dupe`);
        if (summary.error) parts.push(`${summary.error} err`);
        btn.textContent = `Done (${parts.join(", ") || "no changes"})`;
        statusEl.textContent = `${total} of ${total} processed`;
        rescanBtn.disabled = false;
        port.disconnect();
        if (cfg.ok) {
          archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive/${county}`;
          archiveLink.style.display = "inline";
        }
        resolve();
      } else if (msg.type === "error") {
        const li = document.createElement("li");
        li.className = "status-err";
        li.textContent = `Fatal: ${msg.error}`;
        list.appendChild(li);
        btn.textContent = "Retry";
        btn.disabled = false;
        rescanBtn.disabled = false;
        port.disconnect();
        resolve();
      }
    });
  });
}

async function render() {
  list.innerHTML = "";
  progressBar.classList.remove("on");
  archiveLink.style.display = "none";
  statusEl.textContent = "";
  bulkStatusEl.textContent = "";
  btn.textContent = "Upload";
  btn.disabled = true;
  rescanBtn.disabled = false;
  bulkBtn.disabled = true;
  bulkBtn.textContent = "Scan all depts";

  const tab = await activeTab();
  const url = tab?.url || "";
  const host = url ? new URL(url).hostname : "";
  hostEl.textContent = host || "(no tab)";

  const cfg = await getConfigStatus();
  if (cfg.ok) {
    setPill(cfgEl, `✓ ${cfg.owner}/${cfg.repo}`, "ok");
  } else {
    setPill(cfgEl, `✗ missing: ${cfg.missing.join(", ")}`, "err");
  }

  const county = HOST_TO_COUNTY[host];
  if (!county) {
    setPill(countyEl, "not a supported court page", "warn");
    countEl.textContent = "—";
    statusEl.textContent = "Open an EDC or Placer tentative-ruling page.";
    return { county: null, pdfs: [], cfg };
  }
  setPill(countyEl, county, "ok");
  bulkBtn.disabled = !(cfg.ok && BULK_SUPPORTED.has(county));

  const pdfs = await harvestFromTab(tab.id);
  if (pdfs === null) {
    setPill(countEl, "harvest failed", "err");
    statusEl.textContent = "Content script didn't run — try Reload page.";
    return { county, pdfs: [], cfg };
  }
  pdfs.sort((a, b) => (a.filename || a.url).localeCompare(b.filename || b.url));

  if (pdfs.length === 0) {
    setPill(countEl, "0 PDFs", "warn");
    statusEl.textContent = "No PDF links on this page. Try a dept landing page directly.";
    return { county, pdfs: [], cfg };
  }

  setPill(countEl, `${pdfs.length} PDF${pdfs.length === 1 ? "" : "s"}`, "ok");
  statusEl.textContent = cfg.ok
    ? `Ready to upload ${pdfs.length}.`
    : "Set GitHub PAT/owner/repo in Settings before uploading.";
  btn.disabled = !cfg.ok;
  if (cfg.ok) {
    archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive/${county}`;
    archiveLink.style.display = "inline";
  }
  return { county, pdfs, cfg };
}

async function startBulkScan(county, cfg) {
  btn.disabled = true;
  rescanBtn.disabled = true;
  bulkBtn.disabled = true;
  bulkBtn.textContent = "Scanning…";
  bulkStopBtn.style.display = "";
  bulkStopBtn.disabled = false;
  bulkStatusEl.textContent = "Discovering landing pages…";
  list.innerHTML = "";
  statusEl.textContent = "";
  progressBar.classList.add("on");
  progressFill.style.width = "0%";

  let totalPages = 0;
  let pagesDone = 0;
  const summary = { uploaded: 0, "already-captured": 0, "skipped-exists": 0, error: 0 };

  const port = chrome.runtime.connect({ name: "bulk-scan" });
  port.postMessage({ type: "start", county });

  return new Promise((resolve) => {
    const cleanup = () => {
      bulkStopBtn.style.display = "none";
      bulkBtn.disabled = !cfg.ok;
      bulkBtn.textContent = "Scan all depts";
      rescanBtn.disabled = false;
      btn.disabled = currentState.pdfs.length === 0 || !cfg.ok;
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
          ? `Found ${totalPages} landing page${totalPages === 1 ? "" : "s"}.`
          : "No landing pages found.";
      } else if (msg.type === "page-start") {
        bulkStatusEl.textContent = `Page ${msg.index + 1}/${msg.total}: ${msg.title} — loading…`;
        const pct = Math.round((msg.index / Math.max(1, msg.total)) * 100);
        progressFill.style.width = `${pct}%`;
      } else if (msg.type === "page-harvested") {
        bulkStatusEl.textContent = `Page ${msg.index + 1}/${totalPages}: ${msg.title} — ${msg.pdfCount} PDF${msg.pdfCount === 1 ? "" : "s"}`;
        pagesDone = msg.index + 1;
      } else if (msg.type === "page-error") {
        const li = document.createElement("li");
        li.className = "status-err";
        li.textContent = `✗ ${msg.title}: ${msg.error}`;
        list.appendChild(li);
        list.scrollTop = list.scrollHeight;
      } else if (msg.type === "result") {
        appendResult(msg.result);
        summary[msg.result.status] = (summary[msg.result.status] || 0) + 1;
      } else if (msg.type === "done") {
        progressFill.style.width = "100%";
        const parts = [];
        if (summary.uploaded) parts.push(`${summary.uploaded} new`);
        if (summary["skipped-exists"]) parts.push(`${summary["skipped-exists"]} logged`);
        if (summary["already-captured"]) parts.push(`${summary["already-captured"]} dupe`);
        if (summary.error) parts.push(`${summary.error} err`);
        const tag = msg.reason === "stopped" ? "Stopped" : "Done";
        bulkStatusEl.textContent = `${tag} — ${pagesDone}/${totalPages} pages · ${parts.join(", ") || "no changes"}`;
        if (cfg.ok) {
          archiveLink.href = `https://github.com/${cfg.owner}/${cfg.repo}/tree/master/archive/${county}`;
          archiveLink.style.display = "inline";
        }
        cleanup();
      } else if (msg.type === "error") {
        const li = document.createElement("li");
        li.className = "status-err";
        li.textContent = `Fatal: ${msg.error}`;
        list.appendChild(li);
        bulkStatusEl.textContent = `Failed: ${msg.error}`;
        cleanup();
      }
    });
  });
}

let currentState = { county: null, pdfs: [], cfg: { ok: false } };

rescanBtn.addEventListener("click", async () => {
  rescanBtn.disabled = true;
  currentState = await render();
});

btn.addEventListener("click", async () => {
  if (!currentState.county || currentState.pdfs.length === 0 || !currentState.cfg.ok) return;
  await startUpload(currentState.pdfs, currentState.county, currentState.cfg);
});

bulkBtn.addEventListener("click", async () => {
  if (!currentState.county || !currentState.cfg.ok) return;
  if (!BULK_SUPPORTED.has(currentState.county)) return;
  await startBulkScan(currentState.county, currentState.cfg);
});

(async () => {
  console.log("[tentatives popup] opened");
  currentState = await render();
})().catch((e) => {
  console.error("[tentatives popup] fatal", e);
  statusEl.textContent = `Popup error: ${e.message || e}`;
  statusEl.className = "small status-err";
});
