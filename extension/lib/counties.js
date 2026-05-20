// Shared between background.js and sidepanel.js — must be importable from both
// MV3 service-worker and DOM script contexts (plain ES module).
//
// `bulkLandings` is the canonical list the background's "scan all depts"
// action walks for a county. `landings` (per county) drives the sidebar's
// per-page quick-fetch buttons; it's a curated subset for ergonomics.

export const COUNTY_LABEL = {
  "el-dorado":    "El Dorado",
  "placer":       "Placer",
  "contra-costa": "Contra Costa",
};

export const HOST_TO_COUNTY = {
  "eldorado.courts.ca.gov":          "el-dorado",
  "www.eldorado.courts.ca.gov":      "el-dorado",
  "placer.courts.ca.gov":            "placer",
  "www.placer.courts.ca.gov":        "placer",
  "contracosta.courts.ca.gov":       "contra-costa",
  "www.contracosta.courts.ca.gov":   "contra-costa",
  "cc-courts.org":                   "contra-costa",
  "www.cc-courts.org":               "contra-costa",
  "retired.cc-courts.org":           "contra-costa",
};

// Bulk-scan config used by background.js. `landings`, when present, overrides
// the static-href crawl of `root` so iframe-based portals work too.
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
      "https://www.cc-courts.org/civil/motions-hearings-tentative.aspx",
      "https://www.cc-courts.org/civil/motions-hearings-tentative-archive.aspx",
    ],
    pathTest: () => true,
  },
};

// Curated per-county landing-page list for the sidebar's "Pages" section.
// Each entry shows up with a "Go" arrow (navigate active tab) and a "Fetch"
// button (background-fetch + upload without leaving the current tab).
//
// El Dorado has depts 1–12 split across civil/probate/family-law. Listed in
// the order they're most likely to have activity.
export const SIDEBAR_PAGES = {
  "el-dorado": [
    { label: "Dept 4 — Civil / Probate",  url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-4" },
    { label: "Dept 9 — Probate",          url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-9" },
    { label: "Dept 12 — Family Law",      url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-dept-12" },
    { label: "All depts (index)",         url: "https://www.eldorado.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "placer": [
    { label: "Law & Motion",              url: "https://www.placer.courts.ca.gov/online-services/tentative-rulings/tentative-rulings-law-and-motion" },
    { label: "Civil OSC calendar",        url: "https://www.placer.courts.ca.gov/online-services/tentative-rulings/civil-osc-calendar" },
    { label: "Tentative rulings (index)", url: "https://www.placer.courts.ca.gov/online-services/tentative-rulings" },
  ],
  "contra-costa": [
    { label: "Current rulings (shell)",   url: "https://contracosta.courts.ca.gov/online-services/tentative-rulings" },
    { label: "Archive (shell)",           url: "https://contracosta.courts.ca.gov/tentative-rulings-archive" },
    { label: "Current rulings (portal)",  url: "https://www.cc-courts.org/civil/motions-hearings-tentative.aspx" },
    { label: "Archive (portal)",          url: "https://www.cc-courts.org/civil/motions-hearings-tentative-archive.aspx" },
  ],
};

export const DEFAULT_GITHUB = {
  owner:  "aimesy",
  repo:   "tentatives",
  branch: "master",
};
