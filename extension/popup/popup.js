// Popup: lists PDFs detected on the active tab and uploads them to GitHub.

const countyEl = document.getElementById("county");
const countEl = document.getElementById("count");
const btn = document.getElementById("upload");
const list = document.getElementById("results");
document.getElementById("opts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

const HOST_TO_COUNTY = {
  "eldorado.courts.ca.gov": "el-dorado",
  "www.eldorado.courts.ca.gov": "el-dorado",
};

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function harvestFromTab(tabId) {
  // Re-run the harvester in the page context so popup gets fresh state
  // even if the user navigated.
  const [res] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => window.__tentatives_pdfs || [],
  });
  return res?.result || [];
}

(async () => {
  const tab = await activeTab();
  const host = tab?.url ? new URL(tab.url).hostname : "";
  const county = HOST_TO_COUNTY[host];
  if (!county) {
    countyEl.textContent = "Not on a supported court page.";
    countEl.textContent = "";
    return;
  }
  countyEl.textContent = `${county} · ${host}`;

  const pdfs = await harvestFromTab(tab.id);
  countEl.textContent = `${pdfs.length} PDF${pdfs.length === 1 ? "" : "s"} detected`;
  btn.disabled = pdfs.length === 0;

  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Uploading…";
    list.innerHTML = "";
    const resp = await chrome.runtime.sendMessage({
      type: "upload-batch",
      county,
      pdfs,
    });
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
    btn.textContent = `Done (${uploaded} new, ${skipped} dupe)`;
  });
})();
