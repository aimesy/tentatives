// Shared between background.js and sidepanel.js. Plain ES module, importable
// from both the MV3 service worker and DOM script contexts.

export const COUNTY_LABEL = {
  "el-dorado": "El Dorado",
  "placer": "Placer",
  "contra-costa": "Contra Costa",
  "amador": "Amador",
  "san-francisco": "San Francisco",
  "nevada": "Nevada",
  "orange": "Orange",
  "calaveras": "Calaveras",
  "fresno": "Fresno",
  "merced": "Merced",
  "plumas": "Plumas",
  "riverside": "Riverside",
  "san-bernardino": "San Bernardino",
  "santa-clara": "Santa Clara",
  "shasta": "Shasta",
  "solano": "Solano",
  "tuolumne": "Tuolumne",
};

export const HOST_TO_COUNTY = {
  "eldorado.courts.ca.gov": "el-dorado",
  "www.eldorado.courts.ca.gov": "el-dorado",
  "placer.courts.ca.gov": "placer",
  "www.placer.courts.ca.gov": "placer",
  "contracosta.courts.ca.gov": "contra-costa",
  "www.contracosta.courts.ca.gov": "contra-costa",
  "cc-courts.org": "contra-costa",
  "www.cc-courts.org": "contra-costa",
  "retired.cc-courts.org": "contra-costa",
  "amadorcourt.org": "amador",
  "www.amadorcourt.org": "amador",
  "webapps.sftc.org": "san-francisco",
  "nevada.courts.ca.gov": "nevada",
  "www.nevada.courts.ca.gov": "nevada",
  "occourts.org": "orange",
  "www.occourts.org": "orange",
  "calaveras.courts.ca.gov": "calaveras",
  "www.calaveras.courts.ca.gov": "calaveras",
  "fresno.courts.ca.gov": "fresno",
  "www.fresno.courts.ca.gov": "fresno",
  "merced.courts.ca.gov": "merced",
  "www.merced.courts.ca.gov": "merced",
  "plumas.courts.ca.gov": "plumas",
  "www.plumas.courts.ca.gov": "plumas",
  "riverside.courts.ca.gov": "riverside",
  "www.riverside.courts.ca.gov": "riverside",
  "old.sb-court.org": "san-bernardino",
  "santaclara.courts.ca.gov": "santa-clara",
  "www.santaclara.courts.ca.gov": "santa-clara",
  "shasta.courts.ca.gov": "shasta",
  "www.shasta.courts.ca.gov": "shasta",
  "solano.courts.ca.gov": "solano",
  "www.solano.courts.ca.gov": "solano",
  "tuolumne.courts.ca.gov": "tuolumne",
  "www.tuolumne.courts.ca.gov": "tuolumne",
};

export const VOLATILE_URL_COUNTIES = new Set([
  "orange",
  "santa-clara",
  "shasta",
  "tuolumne",
]);

// Bulk-scan config used by background.js. `landings`, when present, overrides
// a static href crawl of `root` so one-page and iframe-driven pages work too.
export const COUNTY_SCAN = {
  "el-dorado": {
    root: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings",
    pathTest: (path) =>
      /^\/online-services\/tentative-rulings\/tentative-rulings-dept-\d+\/?$/i.test(path),
  },
  "placer": {
    root: "https://www.placer.courts.ca.gov/online-services/tentative-rulings",
    pathTest: (path) =>
      /^\/online-services\/tentative-rulings\/[a-z][a-z0-9-]*\/?$/i.test(path)
      && path.replace(/\/$/, "") !== "/online-services/tentative-rulings",
  },
  "contra-costa": {
    root: "https://contracosta.courts.ca.gov/online-services/tentative-rulings",
    landings: [
      "https://contracosta.courts.ca.gov/online-services/tentative-rulings",
      "https://contracosta.courts.ca.gov/tentative-rulings-archive",
      "https://contracosta.courts.ca.gov/probate-calendar",
    ],
    pathTest: () => true,
  },
  "amador": {
    root: "https://www.amadorcourt.org/os-tentativerulings.aspx",
    landings: ["https://www.amadorcourt.org/os-tentativerulings.aspx"],
    pathTest: () => true,
  },
  "san-francisco": {
    root: "https://webapps.sftc.org/ufctr/ufctr.dll",
    landings: ["https://webapps.sftc.org/ufctr/ufctr.dll"],
    pathTest: () => true,
  },
  "nevada": {
    root: "https://www.nevada.courts.ca.gov/online-services/tentative-rulings",
    landings: ["https://www.nevada.courts.ca.gov/online-services/tentative-rulings"],
    pathTest: () => true,
  },
  "orange": {
    root: "https://www.occourts.org/online-services/tentative-rulings",
    landings: [
      "https://www.occourts.org/online-services/tentative-rulings/civil-tentative-rulings",
      "https://www.occourts.org/online-services/tentative-rulings/family-law-tentative-rulings",
      "https://www.occourts.org/online-services/tentative-rulings/probate-tentative-rulings",
    ],
    pathTest: () => true,
  },
  "calaveras": {
    root: "https://www.calaveras.courts.ca.gov/online-services/tentative-rulings",
    landings: [
      "https://www.calaveras.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-case-management",
      "https://www.calaveras.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-civil-law-and-motion-calendar",
    ],
    pathTest: () => true,
  },
  "fresno": {
    root: "https://www.fresno.courts.ca.gov/online-services/tentative-rulings",
    landings: ["https://www.fresno.courts.ca.gov/online-services/tentative-rulings"],
    pathTest: () => true,
  },
  "merced": {
    root: "https://www.merced.courts.ca.gov/online-services/tentative-rulings",
    landings: ["https://www.merced.courts.ca.gov/online-services/tentative-rulings"],
    pathTest: () => true,
  },
  "plumas": {
    root: "https://plumas.courts.ca.gov/online-services/tentative-rulings",
    landings: ["https://plumas.courts.ca.gov/online-services/tentative-rulings"],
    pathTest: () => true,
  },
  "riverside": {
    root: "https://www.riverside.courts.ca.gov/online-services/tentative-rulings",
    landings: ["https://www.riverside.courts.ca.gov/online-services/tentative-rulings"],
    pathTest: () => true,
  },
  "san-bernardino": {
    root: "https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx",
    landings: ["https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx"],
    pathTest: () => true,
  },
  "santa-clara": {
    root: "https://santaclara.courts.ca.gov/online-services/tentative-rulings",
    pathTest: (path) =>
      /^\/online-services\/tentative-rulings\/department-\d+-tentative-rulings\/?$/i.test(path),
  },
  "shasta": {
    root: "https://shasta.courts.ca.gov/online-services/tentative-rulings",
    landings: ["https://shasta.courts.ca.gov/online-services/tentative-rulings"],
    pathTest: () => true,
  },
  "solano": {
    root: "https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings",
    landings: ["https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings"],
    pathTest: () => true,
  },
  "tuolumne": {
    root: "https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes",
    landings: ["https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes"],
    pathTest: () => true,
  },
};

// Curated per-county landing-page list for the sidebar's Pages section.
export const SIDEBAR_PAGES = {
  "el-dorado": [
    { label: "Dept 4 - Civil / Probate", url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-4" },
    { label: "Dept 9 - Probate", url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-9" },
    { label: "Dept 12 - Family Law", url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-12" },
    { label: "All depts (index)", url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "placer": [
    { label: "Law & Motion", url: "https://www.placer.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-law-and-motion" },
    { label: "Civil OSC calendar", url: "https://www.placer.courts.ca.gov/online-services/tentative-rulings/civil-osc-calendar" },
    { label: "Tentative rulings (index)", url: "https://www.placer.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "contra-costa": [
    { label: "Current rulings", url: "https://contracosta.courts.ca.gov/online-services/tentative-rulings" },
    { label: "Rulings archive", url: "https://contracosta.courts.ca.gov/tentative-rulings-archive" },
    { label: "Probate calendar notes", url: "https://contracosta.courts.ca.gov/probate-calendar" },
  ],
  "amador": [
    { label: "Legacy dropdowns", url: "https://www.amadorcourt.org/os-tentativerulings.aspx" },
  ],
  "san-francisco": [
    { label: "UFC family law", url: "https://webapps.sftc.org/ufctr/ufctr.dll" },
  ],
  "nevada": [
    { label: "Tentative rulings", url: "https://www.nevada.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "orange": [
    { label: "Civil", url: "https://www.occourts.org/online-services/tentative-rulings/civil-tentative-rulings" },
    { label: "Family law", url: "https://www.occourts.org/online-services/tentative-rulings/family-law-tentative-rulings" },
    { label: "Probate / mental health", url: "https://www.occourts.org/online-services/tentative-rulings/probate-tentative-rulings" },
  ],
  "calaveras": [
    { label: "Case management", url: "https://www.calaveras.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-case-management" },
    { label: "Civil law and motion", url: "https://www.calaveras.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-civil-law-and-motion-calendar" },
  ],
  "fresno": [
    { label: "Law and motion", url: "https://www.fresno.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "merced": [
    { label: "Civil law and motion", url: "https://www.merced.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "plumas": [
    { label: "Department 2", url: "https://plumas.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "riverside": [
    { label: "Rulings by region", url: "https://www.riverside.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "san-bernardino": [
    { label: "Legacy civil table", url: "https://old.sb-court.org/GeneralInfo/TentativeRulings.aspx" },
  ],
  "santa-clara": [
    { label: "Dept 1", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-1-tentative-rulings" },
    { label: "Dept 2", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-2-tentative-rulings" },
    { label: "Dept 6", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-6-tentative-rulings" },
    { label: "Dept 7", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-7-tentative-rulings" },
    { label: "Dept 10", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-10-tentative-rulings" },
    { label: "Dept 12", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-12-tentative-rulings" },
    { label: "Dept 13", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-13-tentative-rulings" },
    { label: "Dept 16", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-16-tentative-rulings" },
    { label: "Dept 19", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-19-tentative-rulings" },
    { label: "Dept 22", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings/department-22-tentative-rulings" },
    { label: "All depts (index)", url: "https://santaclara.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "shasta": [
    { label: "Departments", url: "https://shasta.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "solano": [
    { label: "Civil departments", url: "https://solano.courts.ca.gov/divisions/civil-court/tentative-rulings" },
  ],
  "tuolumne": [
    { label: "Tentative rulings and case notes", url: "https://www.tuolumne.courts.ca.gov/online-services/tentative-rulings-and-case-notes" },
  ],
};

export const DEFAULT_GITHUB = {
  owner: "aimesy",
  repo: "tentatives",
  branch: "master",
};
