// Content script: runs on EDC tentative-rulings pages, harvests PDF links
// from the DOM and reports them to the background service worker.

(function () {
  const COUNTY = "el-dorado";
  const PDF_PATH_RE = /\/system\/files\/tentative-rulings?\/[^/]+\.pdf$/i;

  function harvest() {
    const seen = new Set();
    const links = [];
    for (const a of document.querySelectorAll("a[href]")) {
      let href;
      try {
        href = new URL(a.href, location.href).href;
      } catch {
        continue;
      }
      if (!PDF_PATH_RE.test(new URL(href).pathname)) continue;
      if (seen.has(href)) continue;
      seen.add(href);
      const filename = href.split("/").pop().split("?")[0];
      links.push({ url: href, filename });
    }
    return links;
  }

  const pdfs = harvest();
  window.__tentatives_pdfs = pdfs;
  console.log(`[tentatives ${COUNTY}] harvested ${pdfs.length} PDFs from ${location.href}`);
  chrome.runtime.sendMessage({
    type: "page-loaded",
    county: COUNTY,
    url: location.href,
    pdfs,
  });
})();
