// Content script for Contra Costa County tentative-ruling pages.
//
// CCC's setup is unusual:
//   - The public landing page (contracosta.courts.ca.gov/online-services/
//     tentative-rulings) is mostly chrome plus an iframe.
//   - The iframe loads cc-courts.org/civil/motions-hearings-tentative.aspx
//     (current week) or .../motions-hearings-tentative-archive.aspx (archive).
//   - That iframe contains many collapsibles (<details>, [aria-expanded], or
//     UI library accordions), and inside them are the PDF links per dept and
//     per hearing date.
//   - PDFs themselves live at cc-courts.org/civil/TR/Department%20NN%20-%20Judge%20.../NN_MMDDYY.pdf
//     (or retired.cc-courts.org/civil/TR/...). A handful of probate rulings
//     are also published at contracosta.courts.ca.gov/system/files/tentative-ruling/.
//
// To get *every* PDF the iframe knows about, we have to expand any
// collapsibles first — many UIs render content lazily on expand. We attempt
// that defensively (idempotent; safe to run on pages without collapsibles)
// before harvesting.
//
// This script runs in every frame on these hosts (all_frames: true in
// manifest), so the parent contracosta.courts.ca.gov frame and the cross-
// origin cc-courts.org iframe both publish their own window.__tentatives_pdfs.
// The popup uses chrome.scripting.executeScript with allFrames: true to merge.

(function () {
  const COUNTY = "contra-costa";

  const ALLOWED_HOSTS = [
    /(^|\.)cc-courts\.org$/i,
    /(^|\.)contracosta\.courts\.ca\.gov$/i,
  ];

  // Path filters per host — keeps incidental PDFs (forms, packets, judicial
  // directories) out of the harvest. Each entry: { hostRe, pathRe }.
  const PDF_PATH_RULES = [
    // cc-courts.org/civil/TR/Department NN - Judge ../NN_MMDDYY.pdf
    {
      hostRe: /(^|\.)cc-courts\.org$/i,
      pathRe: /\/civil\/TR\/.+\.pdf$/i,
    },
    // contracosta.courts.ca.gov/system/files/tentative-ruling/<dept>-<date>.pdf
    // and similar — the "tentative-ruling" segment marks them as rulings.
    {
      hostRe: /(^|\.)contracosta\.courts\.ca\.gov$/i,
      pathRe: /\/system\/files\/tentative-rulings?\/[^/]+\.pdf$/i,
    },
  ];

  // Filenames that match the path rule above but are obviously not rulings
  // (department directories, info sheets, etc.). The parser ultimately filters
  // by PDF header content too, but skipping these here saves a fetch + commit.
  const NON_RULING_NAME_RE =
    /\b(judicial[-_ ]directory|department[-_ ]phone|directory[-_ ]of[-_ ]judicial|phone[-_ ]numbers?)\b/i;

  function isRulingPdf(url) {
    let u;
    try { u = new URL(url); } catch { return false; }
    if (!u.pathname.toLowerCase().endsWith(".pdf")) return false;
    if (!ALLOWED_HOSTS.some((re) => re.test(u.hostname))) return false;
    if (NON_RULING_NAME_RE.test(decodeURIComponent(u.pathname))) return false;
    return PDF_PATH_RULES.some(
      (rule) => rule.hostRe.test(u.hostname) && rule.pathRe.test(u.pathname),
    );
  }

  // Expand collapsibles so any lazy-rendered PDF links are added to the DOM.
  // Conservative: only flips elements from collapsed→expanded; never closes.
  // Returns the count we actually opened so we know whether to wait briefly
  // for late renders.
  function openCollapsibles(root) {
    let opened = 0;

    // 1. Native <details> elements.
    for (const d of root.querySelectorAll("details:not([open])")) {
      d.open = true;
      opened++;
    }

    // 2. aria-expanded toggles (USWDS accordions, generic ARIA accordions,
    //    Drupal collapsibles, etc.). Click rather than poke aria-expanded
    //    directly so the toggling JS still runs.
    const ariaCandidates = root.querySelectorAll(
      'button[aria-expanded="false"], [role="button"][aria-expanded="false"], a[aria-expanded="false"]'
    );
    for (const el of ariaCandidates) {
      try {
        el.click();
        opened++;
      } catch { /* dispatch failure — keep going */ }
    }

    // 3. Common class-based collapsibles seen on .gov sites.
    //    USWDS (.usa-accordion__button), Bootstrap (.panel-heading,
    //    .accordion-button), Drupal (.collapsible). We already caught most
    //    via aria-expanded=false above; this is a belt-and-suspenders pass.
    const classCandidates = root.querySelectorAll(
      ".usa-accordion__button:not([aria-expanded=true]), " +
      ".accordion-button.collapsed, " +
      ".accordion__button:not(.open):not(.expanded):not([aria-expanded=true]), " +
      ".collapsible:not(.open):not(.expanded):not(.is-open), " +
      ".panel-heading:not(.open):not(.expanded)"
    );
    for (const el of classCandidates) {
      try {
        el.click();
        opened++;
      } catch { /* keep going */ }
    }

    return opened;
  }

  function harvest(root) {
    const seen = new Set();
    const links = [];
    for (const a of root.querySelectorAll("a[href]")) {
      let href;
      try {
        href = new URL(a.href, location.href).href;
      } catch { continue; }
      if (!isRulingPdf(href)) continue;
      if (seen.has(href)) continue;
      seen.add(href);
      const filename = decodeURIComponent(href.split("/").pop().split("?")[0]);
      links.push({ url: href, filename });
    }
    return links;
  }

  function report(pdfs) {
    window.__tentatives_pdfs = pdfs;
    try {
      chrome.runtime.sendMessage({
        type: "page-loaded",
        county: COUNTY,
        url: location.href,
        pdfs,
      });
    } catch { /* extension context invalidated, etc. */ }
  }

  // Initial pass.
  const opened = openCollapsibles(document);
  let pdfs = harvest(document);
  report(pdfs);
  console.log(
    `[tentatives ${COUNTY}] frame ${location.href}: harvested ${pdfs.length} PDFs` +
    (opened ? ` (opened ${opened} collapsibles)` : "")
  );

  // After expanding collapsibles, content often pops in on the next tick.
  // Re-harvest a few times so we don't miss late-rendered PDFs. Cheap.
  let attempts = 0;
  const MAX_ATTEMPTS = 6;
  const tick = () => {
    attempts++;
    const more = openCollapsibles(document);
    const next = harvest(document);
    if (next.length !== pdfs.length || more > 0) {
      pdfs = next;
      report(pdfs);
      console.log(`[tentatives ${COUNTY}] re-harvest #${attempts}: ${pdfs.length} PDFs`);
    }
    if (attempts < MAX_ATTEMPTS) {
      setTimeout(tick, 500 + attempts * 250);
    }
  };
  setTimeout(tick, 400);

  // Also watch for late DOM mutations (some sites swap iframe content in).
  const obs = new MutationObserver(() => {
    const next = harvest(document);
    if (next.length !== pdfs.length) {
      pdfs = next;
      report(pdfs);
    }
  });
  obs.observe(document.documentElement || document.body, {
    subtree: true,
    childList: true,
  });
  // Stop observing after ~30s to avoid runaway work on busy pages.
  setTimeout(() => obs.disconnect(), 30000);
})();
