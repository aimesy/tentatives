// Generic static-page PDF harvester for counties whose tentative-ruling pages
// expose direct PDF links or dropdown option values.

(function () {
  const RULES = [
    {
      county: "amador",
      pageHosts: ["amadorcourt.org", "www.amadorcourt.org"],
      pdfHosts: ["amadorcourt.org", "www.amadorcourt.org"],
      includeOptions: true,
      match: (u) => /\/tentativeRulings\/.+\.pdf$/i.test(u.pathname),
      divisionHint: (_u, text, source) => {
        const hay = `${source || ""} ${text || ""}`;
        if (/CivilLawAndMotion|CIVIL LAW/i.test(hay)) return "Civil Law and Motion";
        if (/CivilCaseMgt|CIVIL CASE/i.test(hay)) return "Civil Case Management Conference";
        if (/FamilyLawCaseMgt|FAMILY LAW/i.test(hay)) return "Family Law Case Management";
        if (/ChildSupport|CHILD SUPPORT/i.test(hay)) return "Child Support";
        return null;
      },
    },
    {
      county: "san-francisco",
      pageHosts: ["webapps.sftc.org"],
      pdfHosts: ["webapps.sftc.org"],
      match: (u) => /\/ufctr\/files\/.+tentative.+\.pdf$/i.test(decodeURIComponent(u.pathname)),
      deptHint: (u, text) => {
        const m = `${decodeURIComponent(u.pathname)} ${text || ""}`.match(/Dept\s*(\d{3})|^(\d{3})\s+Tentative/i);
        return m ? (m[1] || m[2]) : null;
      },
      divisionHint: () => "Family Law",
    },
    {
      county: "nevada",
      pageHosts: ["nevada.courts.ca.gov", "www.nevada.courts.ca.gov"],
      pdfHosts: ["nevada.courts.ca.gov", "www.nevada.courts.ca.gov"],
      match: (u, text) =>
        /\/system\/files\/tentative-rulings\/.+\.pdf$/i.test(u.pathname)
        && /tentative/i.test(text || u.pathname),
      divisionHint: (_u, text) => {
        if (/case management|cmc/i.test(text)) return "Case Management";
        if (/family/i.test(text)) return "Family Law";
        if (/probate/i.test(text)) return "Probate";
        if (/guardianship/i.test(text)) return "Guardianship";
        if (/civil|law (?:and|&) motion/i.test(text)) return "Law and Motion";
        return null;
      },
    },
    {
      county: "orange",
      pageHosts: ["occourts.org", "www.occourts.org"],
      pdfHosts: ["occourts.org", "www.occourts.org", "live-jcc-oc.pantheonsite.io"],
      match: (u) => /\/tentative-rulings\/.+\.pdf$/i.test(u.pathname),
      divisionHint: (_u, _text, _source, pageUrl) => {
        const path = pageUrl.pathname.toLowerCase();
        if (path.includes("family-law")) return "Family Law";
        if (path.includes("probate")) return "Probate";
        if (path.includes("civil")) return "Civil";
        return null;
      },
      dateHint: (u, text, _source, pageUrl) =>
        extractDateHint(text, u.pathname, pageUrl.pathname, document.title),
    },
    {
      county: "calaveras",
      pageHosts: ["calaveras.courts.ca.gov", "www.calaveras.courts.ca.gov"],
      pdfHosts: ["calaveras.courts.ca.gov", "www.calaveras.courts.ca.gov"],
      match: (u, text) =>
        /^\/system\/files\/.+\.pdf$/i.test(u.pathname)
        && /tentative|cmc/i.test(text || u.pathname),
      divisionHint: (_u, text, _source, pageUrl) => {
        const hay = `${pageUrl.pathname} ${text || ""}`;
        if (/case-management|cmc/i.test(hay)) return "Case Management";
        if (/civil-law|civil tentative/i.test(hay)) return "Civil Law and Motion";
        return null;
      },
    },
    {
      county: "fresno",
      pageHosts: ["fresno.courts.ca.gov", "www.fresno.courts.ca.gov"],
      pdfHosts: ["fresno.courts.ca.gov", "www.fresno.courts.ca.gov"],
      match: (u) => /\/system\/files\/tentative-rulings\/.+\.pdf$/i.test(u.pathname),
      deptHint: (u) => {
        const m = u.pathname.match(/dept[-_ ]?(\d+)/i);
        return m ? m[1] : null;
      },
      divisionHint: () => "Civil Law and Motion",
    },
    {
      county: "merced",
      pageHosts: ["merced.courts.ca.gov", "www.merced.courts.ca.gov"],
      pdfHosts: ["merced.courts.ca.gov", "www.merced.courts.ca.gov"],
      match: (u) => /\/system\/files\/tentative-rulings\/.+\.pdf$/i.test(u.pathname),
      divisionHint: () => "Civil Law and Motion",
    },
    {
      county: "plumas",
      pageHosts: ["plumas.courts.ca.gov", "www.plumas.courts.ca.gov"],
      pdfHosts: ["plumas.courts.ca.gov", "www.plumas.courts.ca.gov"],
      match: (u) => /\/system\/files\/tentative-ruling\/.+\.pdf$/i.test(u.pathname),
      deptHint: () => "2",
      divisionHint: () => "Civil / Probate / Family Law",
    },
    {
      county: "riverside",
      pageHosts: ["riverside.courts.ca.gov", "www.riverside.courts.ca.gov"],
      pdfHosts: ["riverside.courts.ca.gov", "www.riverside.courts.ca.gov"],
      match: (u, text) =>
        /\.pdf$/i.test(u.pathname) && /ruling/i.test(`${u.pathname} ${text || ""}`),
      deptHint: (u, text) => {
        const m = `${u.pathname} ${text || ""}`.match(/(?:department|dept\.?|^|\/)([A-Z]{1,3}\d{1,3})/i);
        return m ? m[1].toUpperCase() : null;
      },
      divisionHint: () => "Law and Motion",
    },
    {
      county: "san-bernardino",
      pageHosts: ["old.sb-court.org"],
      pdfHosts: ["old.sb-court.org"],
      match: (u) => /\/DesktopModules\/TentativeRulings\/TentativeRulings\/.+\.pdf$/i.test(u.pathname),
      deptHint: (u) => {
        const m = u.pathname.match(/CV([RS]\d{2})\d{6}\.pdf/i);
        return m ? m[1].toUpperCase() : null;
      },
      divisionHint: () => "Civil",
    },
    {
      county: "santa-clara",
      pageHosts: ["santaclara.courts.ca.gov", "www.santaclara.courts.ca.gov"],
      pdfHosts: ["santaclara.courts.ca.gov", "www.santaclara.courts.ca.gov"],
      match: (u) => /\/system\/files\/tentative-ruling\/.+\.pdf$/i.test(u.pathname),
      deptHint: (u, _text, _source, pageUrl) => {
        const m = `${u.pathname} ${pageUrl.pathname}`.match(/(?:dept|department)[-_ ]?(\d+)/i);
        return m ? m[1] : null;
      },
      divisionHint: (_u, _text, _source, pageUrl) => {
        if (/department-(2|7)-/i.test(pageUrl.pathname)) return "Probate";
        if (/department-(19|22)-/i.test(pageUrl.pathname)) return "Complex Civil";
        return "Civil Law and Motion";
      },
      dateHint: (u, text, _source, pageUrl) =>
        extractDateHint(text, u.pathname, pageUrl.pathname, document.title),
    },
    {
      county: "shasta",
      pageHosts: ["shasta.courts.ca.gov", "www.shasta.courts.ca.gov"],
      pdfHosts: ["shasta.courts.ca.gov", "www.shasta.courts.ca.gov"],
      match: (u) => /\/system\/files\/tentative\/.+\.pdf$/i.test(u.pathname),
      deptHint: (u, text) => {
        const hay = `${u.pathname} ${text || ""}`.toLowerCase();
        const direct = hay.match(/department\s+(\d+)/);
        if (direct) return direct[1];
        const map = { d10: "24", d7: "44", d5: "51", d6: "52", d11: "53", d8: "63", d3: "64" };
        for (const [oldDept, currentDept] of Object.entries(map)) {
          if (hay.includes(oldDept)) return currentDept;
        }
        return null;
      },
      divisionHint: () => "Civil / Probate / Family Law",
      dateHint: (u, text, _source, pageUrl) =>
        extractDateHint(text, u.pathname, pageUrl.pathname, document.title),
    },
    {
      county: "solano",
      pageHosts: ["solano.courts.ca.gov", "www.solano.courts.ca.gov"],
      pdfHosts: ["solano.courts.ca.gov", "www.solano.courts.ca.gov"],
      match: (u) => /\/system\/files\/general\/(?:dept_(?:3|7|8|22)|misc_dept)\.pdf$/i.test(u.pathname),
      deptHint: (u, text) => {
        const m = u.pathname.match(/dept_(\d+)/i);
        if (m) return m[1];
        const hay = (text || "").toLowerCase();
        if (hay.includes("twenty-two")) return "22";
        if (hay.includes("three")) return "3";
        if (hay.includes("seven")) return "7";
        if (hay.includes("eight")) return "8";
        return null;
      },
      divisionHint: () => "Civil / Probate",
    },
    {
      county: "tuolumne",
      pageHosts: ["tuolumne.courts.ca.gov", "www.tuolumne.courts.ca.gov"],
      pdfHosts: ["tuolumne.courts.ca.gov", "www.tuolumne.courts.ca.gov"],
      match: (u, text) =>
        /\/system\/files\/tentative-rulings\/.+\.pdf$/i.test(u.pathname),
      deptHint: (u, text) => {
        const m = `${u.pathname} ${text || ""}`.match(
          /(?:department|dept|tr[-_ ]?d|case[-_ ]?notes?[-_ ]?d)(?:[-_ ]?)(\d+)/i,
        );
        return m ? m[1] : null;
      },
      divisionHint: (u, text, source) => {
        const hay = `${u.pathname} ${text || ""} ${source || ""}`;
        if (/case[-_ ]?notes?/i.test(hay)) return "Case Notes";
        return "Civil Law and Motion";
      },
      dateHint: (u, text, _source, pageUrl) =>
        extractDateHint(text, u.pathname, pageUrl.pathname, document.title),
    },
  ];

  function hostMatches(host, hosts) {
    return hosts.some((h) => host === h || host.endsWith(`.${h}`));
  }

  const pageUrl = new URL(location.href);
  const rule = RULES.find((r) => hostMatches(pageUrl.hostname, r.pageHosts));
  if (!rule) return;

  function tryUrl(raw) {
    try {
      return new URL(raw, location.href);
    } catch {
      return null;
    }
  }

  function filenameFor(u) {
    const parts = decodeURIComponent(u.pathname).split("/");
    return parts[parts.length - 1] || "tentative-ruling.pdf";
  }

  function cleanText(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function normalizedYear(value) {
    const text = String(value || "");
    return text.length === 2 ? `20${text}` : text;
  }

  function formatDateHint(year, month, day) {
    const y = Number(normalizedYear(year));
    const m = Number(month);
    const d = Number(day);
    if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d)) return null;
    if (y < 2000 || y > 2100 || m < 1 || m > 12 || d < 1 || d > 31) return null;
    return `${y}-${pad2(m)}-${pad2(d)}`;
  }

  function monthNumber(value) {
    const key = String(value || "").toLowerCase().replace(/\./g, "").slice(0, 3);
    return {
      jan: 1,
      feb: 2,
      mar: 3,
      apr: 4,
      may: 5,
      jun: 6,
      jul: 7,
      aug: 8,
      sep: 9,
      oct: 10,
      nov: 11,
      dec: 12,
    }[key] || null;
  }

  function extractDateHint(...parts) {
    const hay = cleanText(parts.filter(Boolean).join(" "));
    if (!hay) return null;

    let m = hay.match(/\b(20\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b/);
    if (m) return formatDateHint(m[1], m[2], m[3]);

    m = hay.match(/\b(0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])[-/.](20\d{2}|\d{2})\b/);
    if (m) return formatDateHint(m[3], m[1], m[2]);

    m = hay.match(/(?:^|[^\d])(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?=$|[^\d])/);
    if (m) return formatDateHint(m[1], m[2], m[3]);

    m = hay.match(/(?:^|[^\d])(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(20\d{2})(?=$|[^\d])/);
    if (m) return formatDateHint(m[3], m[1], m[2]);

    const monthName = "(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)";
    m = hay.match(new RegExp(`\\b${monthName}\\.?\\s+(\\d{1,2})(?:st|nd|rd|th)?,?\\s+(20\\d{2})\\b`, "i"));
    if (m) return formatDateHint(m[3], monthNumber(m[1]), m[2]);

    m = hay.match(new RegExp(`\\b(\\d{1,2})(?:st|nd|rd|th)?\\s+${monthName}\\.?\\s+(20\\d{2})\\b`, "i"));
    if (m) return formatDateHint(m[3], monthNumber(m[2]), m[1]);

    return null;
  }

  function addCandidate(out, seen, rawUrl, text, source) {
    const u = tryUrl(rawUrl);
    if (!u) return;
    if (!hostMatches(u.hostname, rule.pdfHosts)) return;
    if (!rule.match(u, text, source, pageUrl)) return;
    const href = u.href;
    if (seen.has(href)) return;
    seen.add(href);
    const item = {
      url: href,
      filename: filenameFor(u),
      sourcePageUrl: location.href,
    };
    const labelHint = cleanText(text);
    const pageTitleHint = cleanText(document.title);
    if (labelHint) item.labelHint = labelHint;
    if (pageTitleHint) item.pageTitleHint = pageTitleHint;
    const deptHint = rule.deptHint?.(u, text, source, pageUrl);
    const divisionHint = rule.divisionHint?.(u, text, source, pageUrl);
    const dateHint = rule.dateHint?.(u, text, source, pageUrl);
    if (deptHint) item.deptHint = deptHint;
    if (divisionHint) item.divisionHint = divisionHint;
    if (dateHint) item.dateHint = dateHint;
    out.push(item);
  }

  function harvest() {
    const seen = new Set();
    const links = [];
    for (const a of document.querySelectorAll("a[href]")) {
      addCandidate(links, seen, a.getAttribute("href"), a.textContent || "", "a");
    }
    if (rule.includeOptions) {
      for (const opt of document.querySelectorAll("option[value]")) {
        const select = opt.closest("select");
        const source = `${select?.id || ""} ${select?.name || ""}`;
        addCandidate(links, seen, opt.getAttribute("value"), opt.textContent || "", source);
      }
    }
    return links;
  }

  const pdfs = harvest();
  window.__tentatives_pdfs = pdfs;
  console.log(`[tentatives ${rule.county}] harvested ${pdfs.length} PDFs from ${location.href}`);
  chrome.runtime.sendMessage({
    type: "page-loaded",
    county: rule.county,
    url: location.href,
    pdfs,
  });
})();
