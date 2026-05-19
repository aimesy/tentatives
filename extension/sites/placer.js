// Content script for Placer County tentative-ruling pages.
// Harvests *_Web.pdf links from /sites/default/files/<YYYY-MM>/ and similar paths.

(function () {
  const COUNTY = "placer";
  // Two patterns observed: dated PDFs under /sites/default/files/YYYY-MM/ and
  // legacy paths. Match anything ending in .pdf hosted on placer.courts.ca.gov.
  const ALLOWED_HOST = /(^|\.)placer\.courts\.ca\.gov$/i;

  function harvest() {
    const seen = new Set();
    const links = [];
    for (const a of document.querySelectorAll("a[href]")) {
      let u;
      try {
        u = new URL(a.href, location.href);
      } catch {
        continue;
      }
      if (!ALLOWED_HOST.test(u.hostname)) continue;
      if (!u.pathname.toLowerCase().endsWith(".pdf")) continue;
      const href = u.href;
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
