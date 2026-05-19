// Popup: shows live diagnostic state for the active tab, plus the Upload action.

const $ = (id) => document.getElementById(id);
const hostEl = $("d-host");
const countyEl = $("d-county");
const countEl = $("d-pdfcount");
const cfgEl = $("d-config");
const statusEl = $("status");
const btn = $("upload");
const list = $("results");

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
};

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
    return { ok: true, label: `${githubOwner}/${githubRepo}` };
  }
  const missing = [];
  if (!githubToken) missing.push("PAT");
  if (!githubOwner) missing.push("owner");
  if (!githubRepo) missing.push("repo");
  return { ok: false, label: `missing: ${missing.join(", ")}` };
}

(async () => {
  console.log("[tentatives popup] opened");
  const tab = await activeTab();
  const url = tab?.url || "";
  const host = url ? new URL(url).hostname : "";
  hostEl.textContent = host || "(no tab)";

  const cfg = await getConfigStatus();
  if (cfg.ok) setPill(cfgEl, `✓ ${cfg.label}`, "ok");
  else setPill(cfgEl, `✗ ${cfg.label}`, "err");

  const county = HOST_TO_COUNTY[host];
  if (!county) {
    setPill(countyEl, "not a supported court page", "warn");
    countEl.textContent = "—";
    statusEl.textContent = "Open an EDC tentative-ruling page (e.g. /online-services/tentative-rulings/tentative-rulings-dept-9).";
    return;
  }
  setPill(countyEl, county, "ok");

  const pdfs = await harvestFromTab(tab.id);
  if (pdfs === null) {
    setPill(countEl, "harvest failed", "err");
    statusEl.textContent = "Content script didn't run — try reloading the page.";
    return;
  }

  if (pdfs.length === 0) {
    setPill(countEl, "0 PDFs", "warn");
    statusEl.textContent = "No PDF links on this page. Try a dept landing page directly.";
    return;
  }

  setPill(countEl, `${pdfs.length} PDF${pdfs.length === 1 ? "" : "s"}`, "ok");
  statusEl.textContent = cfg.ok
    ? "Ready to upload."
    : "Set GitHub PAT/owner/repo in Settings before uploading.";
  btn.disabled = !cfg.ok;

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Uploading…";
    statusEl.textContent = "";
    list.innerHTML = "";
    let resp;
    try {
      resp = await chrome.runtime.sendMessage({
        type: "upload-batch",
        county,
        pdfs,
      });
    } catch (e) {
      console.error("[tentatives popup] sendMessage failed", e);
      resp = { ok: false, error: String(e.message || e) };
    }
    if (!resp?.ok) {
      const li = document.createElement("li");
      li.className = "status-err";
      li.textContent = `Error: ${resp?.error || "unknown"}`;
      list.appendChild(li);
      btn.textContent = "Retry";
      btn.disabled = false;
      return;
    }
    for (const r of resp.results) {
      const li = document.createElement("li");
      let cls = "status-ok";
      let label = "✓ uploaded";
      if (r.status === "skipped-exists") {
        cls = "status-skip";
        label = "• already archived";
      } else if (r.status === "error") {
        cls = "status-err";
        label = `✗ ${r.error}`;
      }
      li.className = cls;
      li.textContent = `${label} — ${r.filename}`;
      list.appendChild(li);
    }
    const uploaded = resp.results.filter((r) => r.status === "uploaded").length;
    const skipped = resp.results.filter((r) => r.status === "skipped-exists").length;
    const errored = resp.results.filter((r) => r.status === "error").length;
    btn.textContent = `Done (${uploaded} new${skipped ? `, ${skipped} dupe` : ""}${errored ? `, ${errored} err` : ""})`;
  });
})().catch((e) => {
  console.error("[tentatives popup] fatal", e);
  statusEl.textContent = `Popup error: ${e.message || e}`;
  statusEl.className = "small status-err";
});
