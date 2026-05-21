// California Tentative Rulings - static viewer.
//
// Reads data/<county>/rulings.parquet from the same origin via hyparquet,
// merges everything into one in-memory array, and drives a filter/sort/page
// view. It never downloads the archived PDFs during startup.

// Parser-backed counties. The published viewer also loads site/counties.json
// so this fallback only matters for direct file:// or broken-manifest viewing.
const DEFAULT_COUNTIES = [
  { slug: "el-dorado",    label: "El Dorado" },
  { slug: "contra-costa", label: "Contra Costa" },
  { slug: "placer",       label: "Placer" },
];

let KNOWN_COUNTIES = DEFAULT_COUNTIES;
let COUNTY_LABEL = Object.fromEntries(KNOWN_COUNTIES.map((c) => [c.slug, c.label]));
const FILTER_IDS = ["q", "county", "dept", "outcome", "from", "to"];
const SEARCH_FIELDS = [
  "case_number",
  "case_title",
  "motion_type",
  "outcome_text",
  "body_text",
  "full_text",
];
const SORT_COLUMNS = new Set([
  "county",
  "dept",
  "hearing_date",
  "case_number",
  "case_title",
  "motion_type",
  "outcome",
]);
const SORT_DIRECTIONS = new Set(["asc", "desc"]);
const LINK_PROTOCOLS = new Set(["http:", "https:"]);

const $ = (id) => document.getElementById(id);

const state = {
  rows: [],
  filtered: [],
  filters: {
    q: "",
    county: "",
    dept: "",
    outcome: "",
    from: "",
    to: "",
  },
  sort: { col: "hearing_date", dir: "desc" },
  page: 1,
  pageSize: 100,
};

// ============================================================ LOAD

function setStage(name, value, kind = "active") {
  const id = `stage-${name}`;
  let row = $(id);
  if (!row) {
    row = document.createElement("div");
    row.className = "stage";
    row.id = id;
    const stageName = document.createElement("span");
    stageName.className = "s-name";
    stageName.textContent = name;
    const stageValue = document.createElement("span");
    stageValue.className = "s-val";
    row.append(stageName, stageValue);
    $("stages").appendChild(row);
  }
  row.className = `stage ${kind}`;
  row.querySelector(".s-val").textContent = value;
}

// Production layout (Pages payload): data/ sits next to index.html.
// Dev layout (serve repo root): index.html is at site/, data/ is at repo root.
// First successful HEAD wins; resolved once and reused for every county.
const DATA_ROOT_CANDIDATES = ["data", "../data"];
let resolvedDataRoot = null;
let resolvedDataRootPromise = null;
let parquetModulePromise = null;

async function loadParquetModule() {
  if (!parquetModulePromise) {
    setStage("Engine", "loading parquet reader...", "active");
    // Vendored browser modules keep the published viewer self-contained.
    parquetModulePromise = Promise.all([
      import("./vendor/hyparquet-1.18.1/src/index.js"),
      import("./vendor/hyparquet-compressors-1.1.1.esm.js"),
    ]).then(([parquet, compressorMod]) => {
      setStage("Engine", "ready", "done");
      return { ...parquet, compressors: compressorMod.compressors };
    });
  }
  return parquetModulePromise;
}

async function loadCountyManifest() {
  try {
    const r = await fetch("counties.json", { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const counties = await r.json();
    if (!Array.isArray(counties)) throw new Error("manifest is not an array");
    const valid = counties
      .map((county) => ({
        slug: String(county.slug || "").trim(),
        label: String(county.label || county.slug || "").trim(),
      }))
      .filter((county) => county.slug && county.label);
    if (valid.length) {
      KNOWN_COUNTIES = valid;
      COUNTY_LABEL = Object.fromEntries(valid.map((county) => [county.slug, county.label]));
    }
  } catch (e) {
    console.warn("Using fallback county manifest:", e);
  }
}

async function resolveDataRoot() {
  if (resolvedDataRoot) return resolvedDataRoot;
  if (!resolvedDataRootPromise) {
    resolvedDataRootPromise = (async () => {
      const rootChecks = await Promise.all(DATA_ROOT_CANDIDATES.map(async (root) => {
        const checks = await Promise.all(KNOWN_COUNTIES.map(async (county) => {
          try {
            const r = await fetch(`${root}/${county.slug}/rulings.parquet`, { method: "HEAD" });
            return r.ok;
          } catch {
            return false;
          }
        }));
        return { root, ok: checks.some(Boolean) };
      }));
      const match = rootChecks.find((candidate) => candidate.ok);
      // No data found at either layout. Default to production so the per-county
      // 404 stages render correctly.
      return match?.root || DATA_ROOT_CANDIDATES[0];
    })();
  }
  resolvedDataRoot = await resolvedDataRootPromise;
  return resolvedDataRoot;
}

async function fetchAndParse(county) {
  const root = await resolveDataRoot();
  const url = `${root}/${county.slug}/rulings.parquet`;
  setStage(county.label, "downloading...", "active");
  let head;
  try {
    head = await fetch(url, { method: "HEAD" });
  } catch (e) {
    setStage(county.label, `network error: ${e.message || e}`, "err");
    return [];
  }
  if (head.status === 404) {
    setStage(county.label, "no data yet", "done");
    return [];
  }
  if (!head.ok) {
    setStage(county.label, `HTTP ${head.status}`, "err");
    return [];
  }
  const { asyncBufferFromUrl, parquetReadObjects, compressors } = await loadParquetModule();
  // asyncBufferFromUrl lets hyparquet do range requests; for our small (<1MB)
  // parquets this is mostly equivalent to slurping the whole thing, but is
  // future-proof if a county's file grows.
  const file = await asyncBufferFromUrl({ url });
  setStage(county.label, "parsing...", "active");
  const rows = await parquetReadObjects({ file, compressors });
  setStage(county.label, `${rows.length.toLocaleString()} rulings`, "done");
  return rows;
}

function searchTextForRow(row) {
  return SEARCH_FIELDS
    .map((field) => row[field])
    .filter((value) => value !== null && value !== undefined && value !== "")
    .join(" ")
    .toLowerCase();
}

function normalizeRow(row) {
  return { ...row, _search: searchTextForRow(row) };
}

async function loadAll() {
  await loadCountyManifest();
  setStage("Discover", "checking county parquets in parallel", "active");
  const batches = await Promise.all(KNOWN_COUNTIES.map(async (county) => {
    try {
      const rows = await fetchAndParse(county);
      return rows;
    } catch (e) {
      console.error(`Failed to load ${county.slug}:`, e);
      setStage(county.label, `error: ${e.message || e}`, "err");
      return [];
    }
  }));
  let total = 0;
  for (const rows of batches) {
    // Normalize: hearing_date stored as string ISO; keep as-is for sort.
    state.rows.push(...rows.map(normalizeRow));
    total += rows.length;
  }
  setStage("Discover", `${total.toLocaleString()} total rulings`, "done");
  return total;
}

// ============================================================ FILTER & SORT

function applyFilters() {
  const { q, county, dept, outcome, from, to } = state.filters;
  const needle = q.trim().toLowerCase();

  state.filtered = state.rows.filter((r) => {
    if (county && r.county !== county) return false;
    if (dept && String(r.dept ?? "") !== dept) return false;
    if (outcome && r.outcome !== outcome) return false;
    if (from && (r.hearing_date || "") < from) return false;
    if (to && (r.hearing_date || "") > to) return false;
    if (!needle) return true;
    return r._search.includes(needle);
  });

  // Sort.
  if (!SORT_COLUMNS.has(state.sort.col) || !SORT_DIRECTIONS.has(state.sort.dir)) {
    state.sort = { col: "hearing_date", dir: "desc" };
  }
  const { col, dir } = state.sort;
  const sign = dir === "asc" ? 1 : -1;
  state.filtered.sort((a, b) => {
    const av = a[col] ?? "";
    const bv = b[col] ?? "";
    if (av < bv) return -1 * sign;
    if (av > bv) return  1 * sign;
    return 0;
  });

  state.page = 1;
  render();
  syncUrl();
}

// ============================================================ RENDER

function render() {
  const total = state.filtered.length;
  $("result-count").textContent =
    total === state.rows.length
      ? `${total.toLocaleString()} rulings`
      : `${total.toLocaleString()} of ${state.rows.length.toLocaleString()}`;

  const pageCount = Math.max(1, Math.ceil(total / state.pageSize));
  if (state.page > pageCount) state.page = pageCount;
  $("page-info").textContent = `page ${state.page} / ${pageCount}`;
  $("prev-page").disabled = state.page <= 1;
  $("next-page").disabled = state.page >= pageCount;

  const start = (state.page - 1) * state.pageSize;
  const slice = state.filtered.slice(start, start + state.pageSize);

  const body = $("results-body");
  const fragment = document.createDocumentFragment();
  if (slice.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 8;
    cell.className = "empty";
    cell.textContent = "No rulings match the current filters.";
    row.appendChild(cell);
    fragment.appendChild(row);
  } else {
    for (const [i, row] of slice.entries()) {
      fragment.appendChild(renderRow(row, start + i));
    }
  }
  body.replaceChildren(fragment);

  // Header sort markers.
  for (const th of document.querySelectorAll("thead th[data-col]")) {
    const col = th.dataset.col;
    const marker = th.querySelector(".sort-marker");
    if (col === state.sort.col) {
      th.classList.add("sorted");
      marker.textContent = state.sort.dir === "asc" ? "\u2191" : "\u2193";
    } else {
      th.classList.remove("sorted");
      marker.textContent = "";
    }
  }

  $("stats").textContent =
    `${state.rows.length.toLocaleString()} rulings | ` +
    `${new Set(state.rows.map((r) => r.county)).size} counties`;
}

function appendCell(row, text, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = text ?? "";
  row.appendChild(cell);
  return cell;
}

function classToken(value, fallback = "other") {
  const token = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return token || fallback;
}

function pageNumber(value) {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : null;
}

function safeHttpUrl(raw) {
  const value = String(raw || "").trim();
  if (!/^https?:\/\//i.test(value)) return null;
  try {
    const url = new URL(value);
    return LINK_PROTOCOLS.has(url.protocol) ? url : null;
  } catch {
    return null;
  }
}

function pdfHref(r) {
  const url = safeHttpUrl(r.source_url);
  if (!url) return null;
  const page = pageNumber(r.page_start);
  if (page) url.hash = `page=${page}`;
  return url.href;
}

function sourceLabel(r) {
  if (String(r.style || "").startsWith("html-")) return "Page";
  const source = String(r.source_url || "").split("?", 1)[0].toLowerCase();
  return source.endsWith(".pdf") ? "PDF" : "Source";
}

function renderRow(r, idx) {
  const row = document.createElement("tr");
  row.dataset.idx = String(idx);
  appendCell(row, COUNTY_LABEL[r.county] || r.county || "");
  appendCell(row, r.dept || "");
  appendCell(row, r.hearing_date || "");
  appendCell(row, r.case_number || "", "case");
  const title = appendCell(row, r.case_title || "", "title");
  title.title = r.case_title || "";
  appendCell(row, r.motion_type || "");

  const outcomeCell = appendCell(row, "", "outcome");
  const outcome = document.createElement("span");
  outcome.classList.add("outcome-pill", classToken(r.outcome));
  outcome.textContent = r.outcome || "-";
  outcomeCell.appendChild(outcome);
  if (r.conditional) {
    const cond = document.createElement("span");
    cond.className = "cond";
    cond.title = "ABSENT OBJECTION -> granted";
    cond.textContent = "cond.";
    outcomeCell.appendChild(cond);
  }

  const sourceCell = appendCell(row, "");
  const pdf = pdfHref(r);
  if (pdf) {
    const link = document.createElement("a");
    link.href = pdf;
    link.target = "_blank";
    link.rel = "noopener";
    const page = pageNumber(r.page_start);
    link.textContent = `${sourceLabel(r)}${page ? ` p.${page}` : ""}`;
    sourceCell.appendChild(link);
  } else {
    sourceCell.textContent = "-";
  }
  return row;
}

// ============================================================ DRAWER

function openDrawer(idx) {
  const r = state.filtered[idx];
  if (!r) return;
  $("d-case").textContent = r.case_number || "(no case #)";
  $("d-title").textContent = r.case_title || "";
  const kv = $("d-kv");
  kv.replaceChildren();
  const rows = [
    ["County", COUNTY_LABEL[r.county] || r.county],
    ["Dept", r.dept],
    ["Division", r.division],
    ["Date", r.hearing_date],
    ["Motion", r.motion_type],
    ["Outcome", r.outcome ? r.outcome + (r.conditional ? " (conditional)" : "") : ""],
    ["Continued to", r.continued_to],
    ["Pages", r.page_start ? (r.page_start === r.page_end ? r.page_start : `${r.page_start}-${r.page_end}`) : ""],
    ["Parser", r.parser_version],
  ];
  for (const [key, value] of rows) {
    if (value === null || value === undefined || value === "") continue;
    appendKeyValue(kv, key, value);
  }
  const sourceUrl = safeHttpUrl(r.source_url);
  if (sourceUrl) appendKeyValue(kv, "Source", sourceLabel(r), sourceUrl.href);
  $("d-outcome").textContent = r.outcome_text || "(empty)";
  $("d-full").textContent = r.full_text || r.body_text || "(empty)";
  $("drawer").classList.add("open");
}

function appendKeyValue(list, key, value, href = null) {
  const dt = document.createElement("dt");
  dt.textContent = key;
  const dd = document.createElement("dd");
  if (href) {
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = value;
    dd.appendChild(link);
  } else {
    dd.textContent = value;
  }
  list.append(dt, dd);
}

function closeDrawer() {
  $("drawer").classList.remove("open");
}

// ============================================================ POPULATE FILTERS

function populateFilters() {
  const counties = new Set();
  const depts = new Set();
  const outcomes = new Set();
  for (const r of state.rows) {
    if (r.county)  counties.add(r.county);
    if (r.dept)    depts.add(String(r.dept));
    if (r.outcome) outcomes.add(r.outcome);
  }
  fillSelect("county",
    [...counties].sort().map((c) => ({ v: c, t: COUNTY_LABEL[c] || c })));
  fillSelect("dept",
    [...depts].sort((a, b) => {
      const an = Number(a), bn = Number(b);
      if (Number.isFinite(an) && Number.isFinite(bn)) return an - bn;
      return a.localeCompare(b);
    }).map((d) => ({ v: d, t: d })));
  fillSelect("outcome",
    [...outcomes].sort().map((o) => ({ v: o, t: o })));
}

function fillSelect(id, items) {
  const sel = $(id);
  // Keep the first "All" option.
  sel.length = 1;
  const values = new Set(items.map(({ v }) => v));
  const current = state.filters[id];
  if (current && !values.has(current)) {
    const opt = document.createElement("option");
    opt.value = current;
    opt.textContent = id === "county" ? (COUNTY_LABEL[current] || current) : current;
    sel.appendChild(opt);
  }
  for (const { v, t } of items) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = t;
    sel.appendChild(opt);
  }
}

// ============================================================ URL SYNC

function syncUrl() {
  const params = new URLSearchParams();
  for (const k of FILTER_IDS) {
    const v = state.filters[k];
    if (v) params.set(k, v);
  }
  if (
    SORT_COLUMNS.has(state.sort.col) &&
    SORT_DIRECTIONS.has(state.sort.dir) &&
    (state.sort.col !== "hearing_date" || state.sort.dir !== "desc")
  ) {
    params.set("sort", `${state.sort.col}:${state.sort.dir}`);
  }
  const qs = params.toString();
  const newUrl = qs ? `?${qs}` : window.location.pathname;
  window.history.replaceState(null, "", newUrl);
}

function readUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const k of FILTER_IDS) {
    if (params.has(k)) state.filters[k] = params.get(k);
  }
  const sort = params.get("sort");
  if (sort) {
    const [col, dir] = sort.split(":");
    if (SORT_COLUMNS.has(col) && SORT_DIRECTIONS.has(dir)) {
      state.sort = { col, dir };
    }
  }
}

function pushFiltersToUI() {
  for (const k of FILTER_IDS) {
    const el = $(k);
    if (el) el.value = state.filters[k];
  }
}

// ============================================================ WIRING

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), wait);
  };
}

function wire() {
  const debouncedApplyFilters = debounce(applyFilters, 150);
  for (const id of FILTER_IDS) {
    const el = $(id);
    const updateFilter = () => {
      state.filters[id] = el.value;
      if (id === "q") debouncedApplyFilters();
      else applyFilters();
    };
    if (id === "q") {
      el.addEventListener("input", updateFilter);
      el.addEventListener("keyup", updateFilter);
    } else {
      el.addEventListener("change", updateFilter);
    }
  }

  $("reset").addEventListener("click", () => {
    for (const k of FILTER_IDS) state.filters[k] = "";
    pushFiltersToUI();
    applyFilters();
  });

  $("permalink").addEventListener("click", async () => {
    syncUrl();
    try {
      await navigator.clipboard.writeText(window.location.href);
      $("permalink").textContent = "Copied!";
      setTimeout(() => { $("permalink").textContent = "Copy link"; }, 1200);
    } catch {
      window.alert(window.location.href);
    }
  });

  for (const th of document.querySelectorAll("thead th[data-col]")) {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      if (!SORT_COLUMNS.has(col)) return;
      if (state.sort.col === col) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort.col = col;
        state.sort.dir = "asc";
      }
      applyFilters();
    });
  }

  $("results-body").addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-idx]");
    if (!row) return;
    if (e.target.closest("a")) return; // let PDF link work
    openDrawer(Number(row.dataset.idx));
  });

  $("d-close").addEventListener("click", closeDrawer);
  $("drawer").addEventListener("click", (e) => {
    if (e.target === $("drawer")) closeDrawer();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrawer();
  });

  $("prev-page").addEventListener("click", () => { state.page--; render(); });
  $("next-page").addEventListener("click", () => { state.page++; render(); });
  $("page-size").addEventListener("change", (e) => {
    state.pageSize = Number(e.target.value);
    state.page = 1;
    render();
  });
}

// ============================================================ BOOT

(async () => {
  readUrl();
  pushFiltersToUI();
  try {
    const total = await loadAll();
    if (total === 0) {
      $("loading-msg").textContent = "No rulings published yet.";
      $("loading-banner").classList.add("err");
      return;
    }
    populateFilters();
    pushFiltersToUI();
    wire();
    applyFilters();
    $("loading-banner").hidden = true;
    $("toolbar").hidden = false;
    $("results-wrap").hidden = false;
  } catch (e) {
    console.error(e);
    $("loading-msg").textContent = `Failed to load: ${e.message || e}`;
    $("loading-banner").classList.add("err");
  }
})();
