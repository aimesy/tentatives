// California Tentative Rulings - static viewer.
//
// Reads data/<county>/rulings.parquet from the same origin via hyparquet,
// merges everything into one in-memory array, and drives a filter/sort/page
// view. PDFs aren't downloaded during startup; per-ruling sliced PDFs are
// linked into archive/<county>/rulings/<two-hex>/<ruling_id>.pdf on the
// github.com blob view (which renders inline).
//
// The interface is patterned on aimesy/sfsc: chip toolbar,
// Excel-style per-column filter popups + a modal overlay for the detail
// view + URL-driven state so a permalink reproduces the view.

// ============================================================ CONSTANTS

const DEFAULT_COUNTIES = [
  { slug: "el-dorado",    label: "El Dorado",    code: "ELD" },
  { slug: "contra-costa", label: "Contra Costa", code: "CC"  },
  { slug: "placer",       label: "Placer",       code: "PLA" },
];

let KNOWN_COUNTIES = DEFAULT_COUNTIES;
let COUNTY_LABEL = Object.fromEntries(DEFAULT_COUNTIES.map((c) => [c.slug, c.label]));
let COUNTY_CODE  = Object.fromEntries(DEFAULT_COUNTIES.map((c) => [c.slug, c.code]));
let COUNTY_BY_CODE = Object.fromEntries(DEFAULT_COUNTIES.map((c) => [c.code, c.slug]));

const FILTER_IDS = ["q", "from", "to"];
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

// Columns where the unique-value list is too long to render all at once or
// to default-check. The popup uses search-first UX: nothing is selected
// initially, the list is capped, and Apply with empty selection means
// "no filter" rather than "filter to empty set".
const HIGH_CARDINALITY_FILTER_COLS = new Set(["case_title"]);
const HIGH_CARD_RENDER_CAP = 200;
const COL_FILTER_LABELS = {
  county:      "County",
  dept:        "Dept",
  motion_type: "Motion",
  outcome:     "Outcome",
  case_title:  "Title",
};
// Columns that are user-toggleable in the Columns dropdown. Some columns
// stay always-on (case #, date).
const TOGGLEABLE_COLS = [
  { key: "county",  label: "County",  default: true  },
  { key: "dept",    label: "Dept",    default: true  },
  { key: "title",   label: "Title",   default: true  },
  { key: "mtype",   label: "Motion",  default: true  },
  { key: "outcome", label: "Outcome", default: true  },
  { key: "pdf",     label: "PDF",     default: true  },
  { key: "id",      label: "ID",      default: true  },
  { key: "share",   label: "Link",    default: true  },
];
const COLS_STORAGE_KEY = "tentatives.colVisibility";
const VIEW_MODE_STORAGE_KEY = "tentatives.viewMode";

const $ = (id) => document.getElementById(id);

function readStoredViewMode() {
  try {
    return localStorage.getItem(VIEW_MODE_STORAGE_KEY) === "dossier" ? "dossier" : "table";
  } catch {
    return "table";
  }
}

const state = {
  rows: [],
  filtered: [],
  filters: { q: "", from: "", to: "" },
  // Excel-style per-column filters. Map<col, Set<value>>. Absence means
  // "no filter". An empty Set means "user explicitly unticked everything"
  // matches nothing.
  columnFilters: new Map(),
  loadedCounties: new Map(),
  countyStatus: new Map(),
  countyLoads: new Map(),
  selectedCounties: new Set(),
  sort: { col: "hearing_date", dir: "desc" },
  page: 1,
  pageSize: 100,
  viewMode: readStoredViewMode(),
  selectedRowId: "",
  colVisibility: {},
  pendingFocusId: null, // ?r=<id> to auto-open after load
};

function setCountyStatus(slug, status = "idle", detail = "") {
  state.countyStatus.set(slug, { status, detail });
  const row = $(`county-row-${slug}`);
  if (!row) return;
  row.classList.remove("idle", "downloading", "loaded", "error");
  row.classList.add(status);
  const icon = row.querySelector(".dl-status");
  if (icon) {
    icon.classList.remove("idle", "downloading", "loaded", "error");
    icon.classList.add(status);
  }
  const sub = row.querySelector(".county-sub");
  if (sub) sub.textContent = detail || "not loaded";
}

// ============================================================ LOAD

const DATA_ROOT_CANDIDATES = ["data", "../data"];
let resolvedDataRoot = null;
let resolvedDataRootPromise = null;
let parquetModulePromise = null;

async function loadParquetModule() {
  if (!parquetModulePromise) {
    // County parquet files are produced with DuckDB's default ZSTD
    // compression. hyparquet keeps codecs optional, so load the bundled ZSTD
    // decompressor and pass it through explicitly. Importing the full
    // compressor bundle would also initialize its WASM Snappy fallback,
    // which this viewer's CSP intentionally does not permit.
    parquetModulePromise = Promise.all([
      import("./vendor/hyparquet-1.18.1/src/index.js"),
      import("./vendor/fzstd-0.1.1.esm.js"),
    ]).then(([parquet, codec]) => ({
      ...parquet,
        compressors: { ZSTD: (data) => codec.decompress(new Uint8Array(data)) },
    }));
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
      .map((c) => ({
        slug:  String(c.slug || "").trim(),
        label: String(c.label || c.slug || "").trim(),
        code:  String(c.code || c.slug || "").trim().toUpperCase(),
      }))
      .filter((c) => c.slug && c.label);
    if (valid.length) {
      KNOWN_COUNTIES = valid;
      COUNTY_LABEL = Object.fromEntries(valid.map((c) => [c.slug, c.label]));
      COUNTY_CODE  = Object.fromEntries(valid.map((c) => [c.slug, c.code]));
      COUNTY_BY_CODE = Object.fromEntries(valid.map((c) => [c.code, c.slug]));
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
      return match?.root || DATA_ROOT_CANDIDATES[0];
    })();
  }
  resolvedDataRoot = await resolvedDataRootPromise;
  return resolvedDataRoot;
}

async function fetchAndParse(county) {
  const root = await resolveDataRoot();
  const url = `${root}/${county.slug}/rulings.parquet`;
  if (state.selectedCounties.has(county.slug)) {
    setCountyStatus(county.slug, "downloading", "downloading data file...");
  }
  let res;
  try {
    res = await fetch(url);
  } catch (e) {
    throw new Error(`network error: ${e.message || e}`);
  }
  if (res.status === 404) {
    return [];
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  const buffer = await res.arrayBuffer();
  const { parquetReadObjects, compressors } = await loadParquetModule();
  const file = {
    byteLength: buffer.byteLength,
    async slice(start, end) { return buffer.slice(start, end); },
  };
  if (state.selectedCounties.has(county.slug)) {
    setCountyStatus(county.slug, "downloading", "parsing data file...");
  }
  const rows = await parquetReadObjects({ file, compressors });
  return rows;
}

// ============================================================ ROW NORMALIZATION

function searchTextForRow(row) {
  return SEARCH_FIELDS
    .map((field) => row[field])
    .filter((v) => v !== null && v !== undefined && v !== "")
    .join(" ")
    .toLowerCase();
}

const PENDING_NOTES_RE = /calendar\s+notes\s+are\s+not\s+yet\s+available[\s\S]*check\s+back\s+for\s+updated\s+notes/i;

function inferredStatus(row) {
  if (row.status === "pending") return "pending";
  return PENDING_NOTES_RE.test(previewTextForRow(row)) ? "pending" : "published";
}

// Build the short, share-friendly ruling ID: <CODE>-<YYMMDD>-D<dept>-<seq>.
// Example: ELD-251201-D9-3.
function buildShortId(row) {
  const code = COUNTY_CODE[row.county] || String(row.county || "?").toUpperCase();
  const d = row.hearing_date || "";
  // hearing_date arrives as "YYYY-MM-DD" from the parser. Compact to YYMMDD.
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(d);
  const ymd = m ? `${m[1].slice(2)}${m[2]}${m[3]}` : "000000";
  const dept = row.dept != null && row.dept !== "" ? String(row.dept) : "?";
  const seq = row.ruling_index != null ? String(row.ruling_index) : "?";
  return `${code}-${ymd}-D${dept}-${seq}`;
}

function normalizeRow(row) {
  return {
    ...row,
    status: inferredStatus(row),
    _search: searchTextForRow(row),
    _shortId: buildShortId(row),
    _rowId: row.ruling_id || buildShortId(row),
  };
}

function rebuildRows() {
  state.rows = [];
  for (const rows of state.loadedCounties.values()) state.rows.push(...rows);
  const previousIds = new Set(state.rows.map((row) => row.previous_version_id).filter(Boolean));
  for (const row of state.rows) row._isPreviousVersion = previousIds.has(rowKey(row));
}

function startCountyLoad(slug) {
  const existing = state.countyLoads.get(slug);
  if (existing) {
    setCountyStatus(slug, "downloading", "download in progress...");
    return existing;
  }
  const county = KNOWN_COUNTIES.find((c) => c.slug === slug);
  if (!county) return Promise.resolve();

  setCountyStatus(slug, "downloading", "starting download...");
  const load = (async () => {
    try {
      const rows = (await fetchAndParse(county)).map(normalizeRow);
      if (state.selectedCounties.has(slug)) {
        state.loadedCounties.set(slug, rows);
        setCountyStatus(
          slug,
          "loaded",
          rows.length ? `${rows.length.toLocaleString()} rulings loaded` : "no data yet",
        );
      }
    } catch (e) {
      console.error(`Failed to load ${slug}:`, e);
      if (state.selectedCounties.has(slug)) {
        setCountyStatus(slug, "error", `error: ${e.message || e}`);
      }
    } finally {
      if (state.countyLoads.get(slug) === load) state.countyLoads.delete(slug);
      if (!state.selectedCounties.has(slug)) setCountyStatus(slug, "idle", "not loaded");
      rebuildRows();
      applyFilters();
    }
  })();
  state.countyLoads.set(slug, load);
  return load;
}

function ensureCountiesLoaded({ retryErrors = false } = {}) {
  const wanted = new Set(state.selectedCounties);
  const toRemove = [...state.loadedCounties.keys()].filter((slug) => !wanted.has(slug));

  for (const slug of state.countyLoads.keys()) {
    if (!wanted.has(slug)) setCountyStatus(slug, "idle", "not loaded");
  }

  for (const slug of toRemove) {
    state.loadedCounties.delete(slug);
    setCountyStatus(slug, "idle", "not loaded");
  }

  const loads = [];
  for (const slug of wanted) {
    if (state.loadedCounties.has(slug)) continue;
    const status = state.countyStatus.get(slug)?.status;
    if (status === "error" && !retryErrors) continue;
    loads.push(startCountyLoad(slug));
  }
  rebuildRows();
  applyFilters();
  return Promise.allSettled(loads);
}

// ============================================================ SEARCH (with wildcards)

// Translate user input to a RegExp. Supports * (any sequence) and ? (single char).
// Without wildcards: case-insensitive substring match (delegated to includes()).
function compileSearch(raw) {
  if (!raw) return null;
  const hasWildcard = /[*?]/.test(raw);
  if (!hasWildcard) return { kind: "substr", needle: raw.toLowerCase() };
  // Escape regex metacharacters, then re-introduce * and ?.
  const re = raw
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*")
    .replace(/\?/g, ".");
  return { kind: "regex", re: new RegExp(re, "i") };
}

function matchesSearch(row, compiled) {
  if (!compiled) return true;
  if (compiled.kind === "substr") return row._search.includes(compiled.needle);
  return compiled.re.test(row._search);
}

// ============================================================ FILTER & SORT

function rowColumnValue(row, col) {
  if (col === "county") return row.county || "";
  if (col === "dept") return row.dept == null ? "" : String(row.dept);
  if (col === "case_title") return row.case_title || "";
  if (col === "motion_type") return row.motion_type || "";
  if (col === "outcome") return row.outcome || "";
  return row[col] ?? "";
}

function passesColumnFilters(row) {
  for (const [col, set] of state.columnFilters) {
    if (!(set instanceof Set)) continue;
    if (set.size === 0) return false; // user-emptied matches nothing
    const v = rowColumnValue(row, col);
    if (!set.has(v)) return false;
  }
  return true;
}

function applyFilters() {
  const { q, from, to } = state.filters;
  const compiled = compileSearch(q.trim());

  state.filtered = state.rows.filter((r) => {
    if (r._isPreviousVersion) return false;
    if (from && (r.hearing_date || "") < from) return false;
    if (to && (r.hearing_date || "") > to) return false;
    if (!passesColumnFilters(r)) return false;
    return matchesSearch(r, compiled);
  });

  if (!SORT_COLUMNS.has(state.sort.col) || !SORT_DIRECTIONS.has(state.sort.dir)) {
    state.sort = { col: "hearing_date", dir: "desc" };
  }
  const { col, dir } = state.sort;
  const sign = dir === "asc" ? 1 : -1;
  state.filtered.sort((a, b) => {
    const av = rowColumnValue(a, col);
    const bv = rowColumnValue(b, col);
    // Dept sorts numerically when both sides parse as numbers.
    if (col === "dept") {
      const an = Number(av), bn = Number(bv);
      if (Number.isFinite(an) && Number.isFinite(bn)) {
        return (an - bn) * sign;
      }
    }
    if (av < bv) return -1 * sign;
    if (av > bv) return 1 * sign;
    return 0;
  });

  state.page = 1;
  render();
  renderActiveFilters();
  syncUrl();
}

// ============================================================ RENDER

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

const ARCHIVE_BLOB_BASE = "https://github.com/aimesy/tentatives/blob/master/archive";
function rulingPdfHref(r) {
  if (!r.county || !r.ruling_id) return null;
  const id = String(r.ruling_id);
  const prefix = id.slice(0, 2);
  return `${ARCHIVE_BLOB_BASE}/${r.county}/rulings/${prefix}/${id}.pdf`;
}

function pageRangeLabel(row) {
  const page = pageNumber(row?.page_start);
  const pageEnd = pageNumber(row?.page_end);
  if (!page) return "";
  return pageEnd && pageEnd !== page ? `p.${page}-${pageEnd}` : `p.${page}`;
}

function rawSourceHref(row) {
  const url = safeHttpUrl(row?.source_url);
  if (!url) return null;
  const page = pageNumber(row?.page_start);
  if (page && /\.pdf$/i.test(url.pathname)) {
    url.hash = `page=${page}`;
  }
  return url;
}

function rawSourceLabel(row) {
  const range = pageRangeLabel(row);
  return range ? `Raw ${range}` : "Source";
}

function selectedLoadState() {
  const selected = [...state.selectedCounties];
  const ready = selected.filter((slug) => state.loadedCounties.has(slug)).length;
  const loading = selected.filter((slug) => state.countyLoads.has(slug)).length;
  const failed = selected.filter((slug) => (
    !state.loadedCounties.has(slug) &&
    !state.countyLoads.has(slug) &&
    state.countyStatus.get(slug)?.status === "error"
  )).length;
  const waiting = Math.max(0, selected.length - ready - loading - failed);
  return { total: selected.length, ready, loading, failed, waiting };
}

function updateCountyLoadStatus(loadState) {
  const bar = $("county-load-status");
  const label = $("county-load-label");
  const progress = $("county-load-progress");
  const retry = $("county-load-retry");
  const active = loadState.loading + loadState.waiting;
  const finished = loadState.ready + loadState.failed;
  const countyWord = loadState.total === 1 ? "county" : "counties";

  $("results-wrap").setAttribute("aria-busy", active > 0 ? "true" : "false");
  if (active > 0) {
    bar.hidden = false;
    bar.classList.remove("error");
    label.textContent = `Loading county data - ${finished} of ${loadState.total} ${countyWord} finished`;
    progress.hidden = false;
    progress.max = Math.max(1, loadState.total);
    progress.value = finished;
    retry.hidden = true;
    return;
  }
  if (loadState.failed > 0) {
    bar.hidden = false;
    bar.classList.add("error");
    label.textContent = `${loadState.failed} ${loadState.failed === 1 ? "county file" : "county files"} could not be loaded.`;
    progress.hidden = true;
    retry.hidden = false;
    return;
  }
  bar.hidden = true;
  bar.classList.remove("error");
}

function render() {
  const total = state.filtered.length;
  const loadState = selectedLoadState();
  const loadingSelected = loadState.loading + loadState.waiting > 0;
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

  renderTable(slice, start, loadState);
  if (state.viewMode === "dossier") {
    renderDossier(slice, start, loadState);
  }

  // Sort markers on the headers.
  for (const th of document.querySelectorAll("thead th.sortable")) {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.col === state.sort.col) {
      th.classList.add(state.sort.dir === "asc" ? "sort-asc" : "sort-desc");
    }
  }

  if (state.rows.length === 0) {
    const countyWord = loadState.ready === 1 ? "county" : "counties";
    $("stats").textContent = state.selectedCounties.size === 0
      ? "no counties selected"
      : loadingSelected
        ? `${loadState.ready}/${loadState.total} counties ready`
        : loadState.failed > 0
          ? `county load failed`
          : `0 rulings / ${loadState.ready} ${countyWord}`;
  } else {
    const counties = new Set(state.rows.map((r) => r.county)).size;
    const countyWord = counties === 1 ? "county" : "counties";
    $("stats").textContent =
      `${state.rows.length.toLocaleString()} rulings / ${counties} ${countyWord}` +
      (loadingSelected ? ` / loading ${loadState.ready + loadState.failed} of ${loadState.total}` : "");
  }

  updateCountyLoadStatus(loadState);
  refreshColFilterButtons();
  updateCountiesSummary();
  updateActionAvailability();
  applyColVisibility();
  updateViewStripNote(total, start, slice.length);
  applyViewMode();
}

function updateActionAvailability() {
  const exportBtn = $("export-btn");
  if (!exportBtn) return;
  const hasRows = state.filtered.length > 0;
  exportBtn.disabled = !hasRows;
  exportBtn.title = hasRows
    ? "Download filtered view as CSV"
    : "Load county data or adjust filters before exporting CSV";
}

function emptyMessage(loadState) {
  if (state.selectedCounties.size === 0) {
    return "Open Database Downloads to load one or more county data files.";
  }
  if (loadState.loading + loadState.waiting > 0) return "Results appear as each county data file is ready.";
  if (loadState.failed > 0) return "County data could not be loaded. Retry the failed download.";
  if (state.rows.length === 0) return "Selected county data files contain no rulings.";
  return "No rulings match the current filters.";
}

function buildEmptyState(loadState) {
  const loading = loadState.loading + loadState.waiting > 0;
  const wrap = document.createElement("div");
  wrap.className = `empty-state${loading ? " loading" : ""}${loadState.failed > 0 && !loading ? " error" : ""}`;
  if (loading) {
    const spinner = document.createElement("span");
    spinner.className = "empty-state-spinner";
    spinner.setAttribute("aria-hidden", "true");
    wrap.appendChild(spinner);
  }
  const title = document.createElement("strong");
  title.textContent = loading
    ? `Loading county data (${loadState.ready + loadState.failed}/${loadState.total})`
    : loadState.failed > 0
      ? "County data unavailable"
      : "No rulings to display";
  const detail = document.createElement("span");
  detail.textContent = emptyMessage(loadState);
  wrap.append(title, detail);
  if (loadState.failed > 0 && !loading) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "btn empty-state-retry";
    retry.textContent = "Retry failed";
    retry.addEventListener("click", retryFailedCounties);
    wrap.appendChild(retry);
  }
  return wrap;
}

function rowKey(row) {
  return row?._rowId || row?.ruling_id || row?._shortId || "";
}

function displayCaseTitle(row) {
  return row?.case_title || row?.case_number || "(no case title)";
}

function previewTextForRow(row) {
  return (row?.outcome_text || row?.body_text || row?.full_text || "").trim();
}

function renderTable(slice, start, loadState) {
  const body = $("results-body");
  const fragment = document.createDocumentFragment();
  if (slice.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 10;
    td.className = "no-data";
    td.appendChild(buildEmptyState(loadState));
    tr.appendChild(td);
    fragment.appendChild(tr);
  } else {
    for (const [i, row] of slice.entries()) {
      fragment.appendChild(renderRow(row, start + i, i));
    }
  }
  body.replaceChildren(fragment);
  markSelectedTableRow();
}

function appendCell(tr, text, className = "") {
  const td = document.createElement("td");
  if (className) td.className = className;
  td.textContent = text ?? "";
  tr.appendChild(td);
  return td;
}

function renderRow(r, idx, pageIdx = idx) {
  const fragment = document.createDocumentFragment();
  const tr = document.createElement("tr");
  const par = pageIdx % 2 ? "rec-odd" : "rec-even";
  tr.className = `rec-main ${par}`;
  tr.dataset.idx = String(idx);
  tr.dataset.id  = rowKey(r);
  if (rowKey(r) && rowKey(r) === state.selectedRowId) tr.classList.add("selected-row");

  const countyCell = appendCell(tr, COUNTY_LABEL[r.county] || r.county || "", "col-county");
  countyCell.title = COUNTY_LABEL[r.county] || r.county || "";

  appendCell(tr, r.dept || "", "col-dept");
  appendCell(tr, r.hearing_date || "", "col-date");
  appendCell(tr, r.case_number || "", "col-case");

  const title = document.createElement("td");
  title.className = "col-title";
  if (r.case_title) {
    const titleLink = document.createElement("span");
    titleLink.className = "case-title-link";
    titleLink.dataset.cn = r.case_number || "";
    titleLink.title = "See all loaded tentatives for this case";
    titleLink.textContent = r.case_title;
    title.appendChild(titleLink);
  } else {
    title.textContent = r.case_number || "";
  }
  title.title = r.case_title || r.case_number || "";
  tr.appendChild(title);

  const mtypeCell = document.createElement("td");
  mtypeCell.className = "col-mtype";
  if (r.motion_type) {
    const pill = document.createElement("span");
    pill.className = "mtype-pill";
    pill.textContent = r.motion_type;
    pill.title = r.motion_type;
    mtypeCell.appendChild(pill);
  }
  tr.appendChild(mtypeCell);

  const outcomeCell = document.createElement("td");
  outcomeCell.className = "col-outcome";
  const outPill = document.createElement("span");
  const displayOutcome = r.status === "pending" ? "pending" : (r.outcome || "-");
  outPill.className = `outcome-pill outcome-${classToken(displayOutcome)}`;
  outPill.textContent = displayOutcome;
  outcomeCell.appendChild(outPill);
  if (r.conditional) {
    const cond = document.createElement("span");
    cond.className = "cond";
    cond.title = "ABSENT OBJECTION -> granted";
    cond.textContent = "cond.";
    outcomeCell.appendChild(cond);
  }
  tr.appendChild(outcomeCell);

  // PDF cell.
  const pdfCell = document.createElement("td");
  pdfCell.className = "col-pdf";
  const pdfHref = rulingPdfHref(r);
  const sourceHref = rawSourceHref(r);
  if (pdfHref || sourceHref) {
    const links = document.createElement("span");
    links.className = "pdf-links";
    const range = pageRangeLabel(r);
    const a = document.createElement("a");
    if (pdfHref) {
      a.href = pdfHref;
      a.target = "_blank";
      a.rel = "noopener";
      a.className = "pdf-btn";
      a.title = range
        ? `Open per-ruling archived slice; raw source range ${range}`
        : "Open per-ruling archived slice";
      a.textContent = "Slice";
      links.appendChild(a);
    }
    if (sourceHref) {
      const source = document.createElement("a");
      source.href = sourceHref.href;
      source.target = "_blank";
      source.rel = "noopener";
      source.className = "pdf-btn raw-source-btn";
      source.title = range
        ? `Open raw court PDF at ${range}`
        : "Open raw court source";
      source.textContent = rawSourceLabel(r);
      links.appendChild(source);
    }
    pdfCell.appendChild(links);
  } else {
    pdfCell.textContent = "-";
  }
  tr.appendChild(pdfCell);

  appendCell(tr, r._shortId, "col-id");

  // Share/chain button.
  const shareCell = document.createElement("td");
  shareCell.className = "col-share";
  const shareBtn = document.createElement("button");
  shareBtn.className = "share-btn";
  shareBtn.title = "Copy a permalink to this ruling";
  shareBtn.dataset.share = "1";
  shareBtn.textContent = "URL";
  shareCell.appendChild(shareBtn);
  tr.appendChild(shareCell);

  const sub = document.createElement("tr");
  sub.className = `ruling-subrow ${par}`;
  sub.dataset.idx = String(idx);
  sub.dataset.id = rowKey(r);
  if (rowKey(r) && rowKey(r) === state.selectedRowId) sub.classList.add("selected-row");
  const subCell = document.createElement("td");
  subCell.colSpan = 10;
  const excerptBox = document.createElement("div");
  excerptBox.className = "ruling-excerpt";
  const subPreviewText = previewTextForRow(r);
  if (subPreviewText) {
    excerptBox.textContent = subPreviewText;
  } else {
    const empty = document.createElement("span");
    empty.className = "ruling-empty";
    empty.textContent = "no ruling text";
    excerptBox.appendChild(empty);
  }
  subCell.appendChild(excerptBox);
  sub.appendChild(subCell);

  fragment.append(tr, sub);
  return fragment;
}

function currentPageRows() {
  const total = state.filtered.length;
  const pageCount = Math.max(1, Math.ceil(total / state.pageSize));
  if (state.page > pageCount) state.page = pageCount;
  const start = (state.page - 1) * state.pageSize;
  return { start, slice: state.filtered.slice(start, start + state.pageSize) };
}

function setViewMode(mode, { persist = true } = {}) {
  state.viewMode = mode === "dossier" ? "dossier" : "table";
  if (persist) {
    try { localStorage.setItem(VIEW_MODE_STORAGE_KEY, state.viewMode); } catch { /* ignore */ }
  }
  if (state.viewMode === "dossier") {
    const { slice } = currentPageRows();
    ensureDossierSelection(slice);
  }
  render();
  syncUrl();
}

function applyViewMode() {
  const showDossier = state.viewMode === "dossier";
  const tableWrap = $("table-wrap");
  const dossierWrap = $("dossier-wrap");
  if (tableWrap) tableWrap.hidden = showDossier;
  if (dossierWrap) dossierWrap.classList.toggle("open", showDossier);
  const resultsWrap = $("results-wrap");
  if (resultsWrap) resultsWrap.classList.toggle("dossier-mode", showDossier);
  for (const btn of document.querySelectorAll("[data-view-mode]")) {
    const active = btn.dataset.viewMode === state.viewMode;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  }
  markSelectedTableRow();
}

function updateViewStripNote(total, start, shown) {
  const note = $("view-strip-note");
  if (!note) return;
  if (!total) {
    note.textContent = "";
    return;
  }
  note.textContent = `${(start + 1).toLocaleString()}-${(start + shown).toLocaleString()} of ${total.toLocaleString()}`;
}

function ensureDossierSelection(slice) {
  if (!slice.length) {
    state.selectedRowId = "";
    return null;
  }
  const selected = state.selectedRowId && slice.find((r) => rowKey(r) === state.selectedRowId);
  if (selected) return selected;
  state.selectedRowId = rowKey(slice[0]);
  return slice[0];
}

function markSelectedTableRow() {
  const selected = state.selectedRowId;
  const body = $("results-body");
  if (!body) return;
  for (const row of body.querySelectorAll("tr[data-id]")) {
    row.classList.toggle("selected-row", !!selected && row.dataset.id === selected);
  }
}

function selectRuling(row, idx) {
  if (!row) return;
  if (state.viewMode !== "dossier") {
    openModal(row);
    return;
  }
  state.selectedRowId = rowKey(row);
  const { start, slice } = currentPageRows();
  renderDossier(slice, start, selectedLoadState());
  markSelectedTableRow();
  syncUrl();
}

function renderDossier(slice, start, loadState) {
  const rail = $("dossier-rail");
  const railHead = $("dossier-rail-head");
  const detail = $("dossier-detail");
  if (!rail || !detail) return;
  if (!slice.length) {
    rail.replaceChildren();
    if (railHead) railHead.textContent = "Current page";
    const empty = document.createElement("div");
    empty.className = "dossier-empty";
    empty.appendChild(buildEmptyState(loadState));
    detail.replaceChildren(empty);
    return;
  }

  const selected = ensureDossierSelection(slice);
  if (railHead) {
    const end = start + slice.length;
    railHead.textContent = `${(start + 1).toLocaleString()}-${end.toLocaleString()} of ${state.filtered.length.toLocaleString()}`;
  }

  const fragment = document.createDocumentFragment();
  for (const [i, row] of slice.entries()) {
    const div = document.createElement("div");
    div.className = "dossier-row";
    if (rowKey(row) === state.selectedRowId) div.classList.add("active");
    div.dataset.idx = String(start + i);

    const date = document.createElement("div");
    date.className = "dossier-row-date";
    date.textContent = row.hearing_date || "";
    const dept = document.createElement("span");
    dept.textContent = row.dept ? `D${row.dept}` : (COUNTY_CODE[row.county] || "");
    date.append(document.createElement("br"), dept);

    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "dossier-row-title";
    title.textContent = displayCaseTitle(row);
    const motion = document.createElement("div");
    motion.className = "dossier-row-motion";
    motion.textContent = row.motion_type || row.outcome || "";
    body.append(title, motion);

    div.append(date, body);
    div.addEventListener("click", () => {
      state.selectedRowId = rowKey(row);
      renderDossier(slice, start, selectedLoadState());
      markSelectedTableRow();
      syncUrl();
    });
    fragment.appendChild(div);
  }
  rail.replaceChildren(fragment);
  renderDossierDetail(selected || slice[0]);
}

function dossierSection(n, title, bodyHtml) {
  return `<section class="dossier-section">`
    + `<div class="dossier-section-label">${esc(n)}</div>`
    + `<div class="dossier-section-body">`
    + `<div class="section-label">${esc(title)}</div>`
    + bodyHtml
    + `</div></section>`;
}

function previousVersionRows(row) {
  const versions = [];
  const seen = new Set();
  let previousId = row?.previous_version_id;
  while (previousId && !seen.has(previousId)) {
    seen.add(previousId);
    const previous = findRowById(previousId);
    if (!previous) break;
    versions.push(previous);
    previousId = previous.previous_version_id;
  }
  return versions;
}

function previousVersionsHtml(row) {
  const versions = previousVersionRows(row);
  if (!versions.length) return "";
  return `<details class="previous-versions"><summary>Previous version${versions.length === 1 ? "" : "s"}</summary>`
    + versions.map((version) => `<article class="previous-version">`
      + `<div class="previous-version-meta">${esc(version.ingest_ts || version.hearing_date || version._shortId || "Earlier capture")}</div>`
      + `<div>${esc(previewTextForRow(version) || "(empty)")}</div>`
      + `</article>`).join("")
    + `</details>`;
}

function renderDossierDetail(row) {
  const detail = $("dossier-detail");
  if (!detail || !row) return;
  const pdfHref = rulingPdfHref(row);
  const sourceUrl = rawSourceHref(row);
  const outcomeLabel = row.status === "pending" ? "pending" : (row.outcome || "Unknown");
  const outcomeText = row.outcome_text || "(empty)";
  const fullText = row.full_text || row.body_text || "(empty)";
  const range = pageRangeLabel(row);
  const meta = [
    row.case_number,
    COUNTY_LABEL[row.county] || row.county,
    row.dept ? `Dept ${row.dept}` : "",
    row.division || "",
    row.hearing_date || "",
    row._shortId || "",
  ].filter(Boolean);

  detail.innerHTML =
    `<div class="dossier-head">`
    + `<div class="dossier-head-line">`
    + `<span class="dossier-kicker">${esc(COUNTY_CODE[row.county] || row.county || "CA")}</span>`
    + `<span class="outcome-pill outcome-${esc(classToken(outcomeLabel))}">${esc(outcomeLabel)}</span>`
    + (row.conditional ? `<span class="cond">conditional</span>` : "")
    + `</div>`
    + `<h2 class="dossier-title">${esc(displayCaseTitle(row))}</h2>`
    + `<div class="dossier-meta">${meta.map((m) => `<span>${esc(m)}</span>`).join("")}</div>`
    + `<div class="dossier-actions">`
    + `<button type="button" class="btn" data-dossier-open-modal>Open modal</button>`
    + `<button type="button" class="btn" data-dossier-share>Copy link</button>`
    + (row.case_number ? `<button type="button" class="btn" data-dossier-case-history>Case history</button>` : "")
    + (pdfHref ? `<a class="btn" href="${esc(pdfHref)}" target="_blank" rel="noopener">Slice PDF</a>` : "")
    + (sourceUrl ? `<a class="btn" href="${esc(sourceUrl.href)}" target="_blank" rel="noopener">${esc(rawSourceLabel(row))}</a>` : "")
    + `</div></div>`
    + dossierSection("M", "Motion", `<div class="dossier-motion">${esc(row.motion_type || "")}</div>`)
    + dossierSection("1", "Disposition", `<div class="dossier-ruling">${esc(outcomeText)}</div>`)
    + dossierSection("T", "Full text", `<div class="dossier-ruling">${esc(fullText)}</div>`)
    + previousVersionsHtml(row)
    + `<div class="dossier-foot">source: parsed ruling row${range ? `; raw source ${esc(range)}` : ""} &middot; derived: outcome label</div>`;

  detail.querySelector("[data-dossier-open-modal]")?.addEventListener("click", () => openModal(row));
  detail.querySelector("[data-dossier-share]")?.addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    const ok = await copyText(modalUrlFor(row));
    if (ok) flashCopied(btn, "Copy link");
    else window.alert(modalUrlFor(row));
  });
  detail.querySelector("[data-dossier-case-history]")?.addEventListener("click", () => openCaseHistory(row.case_number, row));
}

// ============================================================ MODAL

function modalUrlFor(idOrRow, county = "") {
  const isRow = typeof idOrRow === "object" && idOrRow !== null;
  const id = isRow ? rowKey(idOrRow) : idOrRow;
  const rowCounty = isRow ? idOrRow.county : county;
  const u = new URL(window.location.href);
  u.searchParams.set("r", id);
  if (rowCounty) u.searchParams.set("counties", rowCounty);
  return u.toString();
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function flashCopied(el, original) {
  el.classList.add("copied");
  const before = original ?? el.textContent;
  el.textContent = "Copied!";
  setTimeout(() => {
    el.classList.remove("copied");
    el.textContent = before;
  }, 1200);
}

function openModal(rowOrIdx) {
  const r = typeof rowOrIdx === "number" ? state.filtered[rowOrIdx] : rowOrIdx;
  if (!r) return;
  state.selectedRowId = rowKey(r);
  markSelectedTableRow();
  $("modal-title").textContent = r.case_title || "(no case title)";
  const meta = $("modal-meta");
  meta.replaceChildren();
  const pills = [
    { label: r.case_number || "(no case #)" },
    { label: COUNTY_LABEL[r.county] || r.county },
    r.dept ? { label: `Dept ${r.dept}` } : null,
    r.division ? { label: r.division } : null,
    r.hearing_date ? { label: r.hearing_date } : null,
    { label: r.status === "pending" ? "pending" : ((r.outcome || "other") + (r.conditional ? " (conditional)" : "")) },
    r.continued_to ? { label: `continued -> ${r.continued_to}` } : null,
  ].filter(Boolean);
  for (const p of pills) {
    const span = document.createElement("span");
    span.className = "pill";
    span.textContent = p.label;
    meta.appendChild(span);
  }
  $("modal-motion").textContent = r.motion_type || "";
  $("modal-outcome").textContent = r.outcome_text || "(empty)";
  $("modal-full").textContent = r.full_text || r.body_text || "(empty)";
  const oldVersions = $("modal-previous-versions");
  if (oldVersions) oldVersions.innerHTML = previousVersionsHtml(r);
  $("modal-id").textContent = r._shortId;

  const pdfHref = rulingPdfHref(r);
  const pdfBtn = $("modal-pdf");
  if (pdfHref) {
    pdfBtn.href = pdfHref;
    pdfBtn.textContent = "Slice PDF";
    pdfBtn.hidden = false;
  } else {
    pdfBtn.hidden = true;
  }
  const sourceUrl = rawSourceHref(r);
  const sourceBtn = $("modal-source");
  if (sourceUrl) {
    sourceBtn.href = sourceUrl.href;
    sourceBtn.textContent = rawSourceLabel(r);
    sourceBtn.hidden = false;
  } else {
    sourceBtn.hidden = true;
  }

  $("modal-share").dataset.id = rowKey(r);
  $("modal-share").dataset.county = r.county || "";
  $("overlay").classList.add("open");
  // Reflect open state in the URL so a refresh keeps the modal open.
  const u = new URL(window.location.href);
  if (state.viewMode === "dossier") u.searchParams.set("view", "dossier");
  if (state.selectedRowId) u.searchParams.set("sel", state.selectedRowId);
  u.searchParams.set("r", rowKey(r));
  window.history.replaceState(null, "", u.pathname + (u.search || "") + u.hash);
}

function closeModal() {
  $("overlay").classList.remove("open");
  const u = new URL(window.location.href);
  if (u.searchParams.has("r")) {
    u.searchParams.delete("r");
    window.history.replaceState(null, "", u.pathname + (u.search ? `?${u.searchParams.toString()}` : "") + u.hash);
  }
}

function findRowById(id) {
  if (!id) return null;
  for (const r of state.rows) {
    if (rowKey(r) === id || r._shortId === id) return r;
  }
  return null;
}

function closeCaseHistory() {
  $("case-overlay")?.classList.remove("open");
}

function openCaseHistory(caseNumber, currentRow) {
  if (!caseNumber) return;
  const titleEl = $("case-title");
  const metaEl = $("case-meta");
  const listEl = $("case-history-list");
  if (!titleEl || !metaEl || !listEl) return;

  const matches = state.rows
    .filter((row) => String(row.case_number || "") === String(caseNumber || ""))
    .sort((a, b) => {
      const ad = `${a.hearing_date || ""} ${a.dept || ""}`;
      const bd = `${b.hearing_date || ""} ${b.dept || ""}`;
      return bd.localeCompare(ad);
    });

  titleEl.textContent = currentRow ? displayCaseTitle(currentRow) : `Case ${caseNumber}`;
  metaEl.replaceChildren();
  for (const label of [
    caseNumber,
    `${matches.length} ruling${matches.length === 1 ? "" : "s"} in loaded data`,
  ]) {
    const span = document.createElement("span");
    span.className = "pill";
    span.textContent = label;
    metaEl.appendChild(span);
  }

  const fragment = document.createDocumentFragment();
  if (!matches.length) {
    const empty = document.createElement("div");
    empty.className = "ch-empty";
    empty.textContent = "No rulings found for this case in loaded county data.";
    fragment.appendChild(empty);
  } else {
    for (const [i, row] of matches.entries()) {
      const item = document.createElement("div");
      item.className = "ch-row";
      if (currentRow && rowKey(row) === rowKey(currentRow)) item.classList.add("ch-current");
      item.dataset.idx = String(i);
      item.title = "Click to open this ruling";

      const date = document.createElement("div");
      date.className = "ch-date";
      date.textContent = row.hearing_date || "";

      const county = document.createElement("div");
      county.className = "ch-county";
      county.textContent = COUNTY_CODE[row.county] || row.county || "";

      const dept = document.createElement("div");
      dept.className = "ch-dept";
      dept.textContent = row.dept ? `Dept ${row.dept}` : "";

      const motion = document.createElement("div");
      motion.className = "ch-motion";
      motion.textContent = row.motion_type || displayCaseTitle(row);

      const outcome = document.createElement("div");
      outcome.className = "ch-outcome";
      const pill = document.createElement("span");
      pill.className = `outcome-pill outcome-${classToken(row.outcome)}`;
      pill.textContent = row.outcome || "";
      outcome.appendChild(pill);

      item.append(date, county, dept, motion, outcome);
      item.addEventListener("click", () => {
        closeCaseHistory();
        state.selectedRowId = rowKey(row);
        openModal(row);
        markSelectedTableRow();
        syncUrl();
      });
      fragment.appendChild(item);
    }
  }

  listEl.replaceChildren(fragment);
  $("case-overlay")?.classList.add("open");
}

// ============================================================ COLUMN FILTERS

let _openColFilter = null;

// Compute unique-value buckets for a column from the currently loaded rows.
// Returns [{value, count}, ...] sorted by count desc.
function uniqueValuesFor(col) {
  const counts = new Map();
  for (const r of state.rows) {
    const v = rowColumnValue(r, col);
    counts.set(v, (counts.get(v) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => b.count - a.count || String(a.value).localeCompare(String(b.value)));
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
  }[c]));
}

function openColFilter(col, btn) {
  const pop = $("col-filter-pop");
  _openColFilter = col;
  const rect = btn.getBoundingClientRect();
  pop.style.left = `${Math.min(window.innerWidth - 290, Math.max(8, rect.left + window.scrollX - 8))}px`;
  pop.style.top  = `${rect.bottom + window.scrollY + 4}px`;

  const label = COL_FILTER_LABELS[col] || col;
  pop.innerHTML =
    `<div class="cf-title">Filter - ${esc(label)}</div>` +
    `<div class="cf-sort">` +
      `<button class="cf-az">A to Z</button>` +
      `<button class="cf-za">Z to A</button>` +
      `<button class="cf-byn active">By count</button>` +
    `</div>` +
    `<input class="cf-search" type="search" placeholder="Search values...">` +
    `<div class="cf-list"></div>` +
    `<div class="cf-actions">` +
      `<button class="cf-apply">Apply</button>` +
      `<button class="cf-clear">Clear</button>` +
      `<button class="cf-cancel">Cancel</button>` +
    `</div>`;
  pop.classList.add("open");

  const pairs = uniqueValuesFor(col);
  const isHighCard = HIGH_CARDINALITY_FILTER_COLS.has(col);
  const existing = state.columnFilters.get(col);
  const selected = existing instanceof Set
    ? new Set(existing)
    : (isHighCard ? new Set() : new Set(pairs.map((p) => p.value)));
  let sortMode = isHighCard ? "az" : "count";
  let search = "";

  if (isHighCard) {
    setTimeout(() => pop.querySelector(".cf-search")?.focus(), 0);
    pop.querySelector(".cf-search").placeholder = "Type to search titles...";
  }

  function setSortBtn() {
    for (const b of pop.querySelectorAll(".cf-sort button")) b.classList.remove("active");
    if (sortMode === "az")   pop.querySelector(".cf-az").classList.add("active");
    if (sortMode === "za")   pop.querySelector(".cf-za").classList.add("active");
    if (sortMode === "count") pop.querySelector(".cf-byn").classList.add("active");
  }

  function renderList() {
    setSortBtn();
    const listEl = pop.querySelector(".cf-list");
    let view = pairs.slice();
    if (sortMode === "az") view.sort((a, b) => String(a.value).localeCompare(String(b.value)));
    else if (sortMode === "za") view.sort((a, b) => String(b.value).localeCompare(String(a.value)));
    else view.sort((a, b) => b.count - a.count);
    if (search) {
      const q = search.toLowerCase();
      view = view.filter((p) => String(p.value).toLowerCase().includes(q));
    }
    if (!view.length) {
      if (isHighCard && !search && selected.size > 0) {
        view = pairs.filter((p) => selected.has(p.value));
      }
      if (!view.length) {
        listEl.innerHTML = isHighCard && !search
          ? '<div class="cf-empty">Type to search titles, then tick.</div>'
          : '<div class="cf-empty">No matching values.</div>';
        return;
      }
    }
    let truncatedNote = "";
    if (isHighCard && view.length > HIGH_CARD_RENDER_CAP) {
      truncatedNote = `<div class="cf-empty" style="text-align:left;padding:0.3rem 0.5rem;color:#888">` +
        `Showing ${HIGH_CARD_RENDER_CAP} of ${view.length.toLocaleString()} matches - refine your search.</div>`;
      view = view.slice(0, HIGH_CARD_RENDER_CAP);
    }
    const allChecked = view.every((p) => selected.has(p.value));
    let html = truncatedNote +
      `<label class="cf-row cf-all">` +
        `<input type="checkbox" class="cf-all-cb"${allChecked ? " checked" : ""}>` +
        `<span class="cf-label">(Select all${search || isHighCard ? " visible" : ""})</span>` +
      `</label>`;
    for (const p of view) {
      const display = p.value === "" ? "(blank)" : p.value;
      html +=
        `<label class="cf-row" data-value="${esc(p.value)}">` +
          `<input type="checkbox"${selected.has(p.value) ? " checked" : ""}>` +
          `<span class="cf-label" title="${esc(p.value)}">${esc(display)}</span>` +
          `<span class="cf-count">${p.count.toLocaleString()}</span>` +
        `</label>`;
    }
    listEl.innerHTML = html;

    listEl.querySelector(".cf-all-cb").addEventListener("change", (e) => {
      const on = e.target.checked;
      for (const p of view) {
        if (on) selected.add(p.value); else selected.delete(p.value);
      }
      renderList();
    });
    for (const row of listEl.querySelectorAll(".cf-row[data-value]")) {
      const cb = row.querySelector("input");
      cb.addEventListener("change", () => {
        const v = row.dataset.value;
        if (cb.checked) selected.add(v); else selected.delete(v);
      });
    }
  }
  renderList();

  pop.querySelector(".cf-search").addEventListener("input", (e) => {
    search = e.target.value;
    renderList();
  });
  pop.querySelector(".cf-az").addEventListener("click", () => { sortMode = "az"; renderList(); });
  pop.querySelector(".cf-za").addEventListener("click", () => { sortMode = "za"; renderList(); });
  pop.querySelector(".cf-byn").addEventListener("click", () => { sortMode = "count"; renderList(); });

  pop.querySelector(".cf-apply").addEventListener("click", () => {
    if (selected.size === pairs.length) {
      state.columnFilters.delete(col);
    } else if (selected.size === 0) {
      if (isHighCard) state.columnFilters.delete(col);
      else state.columnFilters.set(col, new Set());
    } else {
      state.columnFilters.set(col, new Set(selected));
    }
    closeColFilter();
    applyFilters();
  });
  pop.querySelector(".cf-clear").addEventListener("click", () => {
    state.columnFilters.delete(col);
    closeColFilter();
    applyFilters();
  });
  pop.querySelector(".cf-cancel").addEventListener("click", closeColFilter);
}

function closeColFilter() {
  $("col-filter-pop").classList.remove("open");
  _openColFilter = null;
}

function refreshColFilterButtons() {
  for (const btn of document.querySelectorAll(".col-filter-btn")) {
    const col = btn.dataset.filterCol;
    btn.classList.toggle("active", state.columnFilters.has(col));
  }
}

// ============================================================ ACTIVE FILTERS BAR

function renderActiveFilters() {
  const bar = $("active-filters");
  bar.replaceChildren();
  for (const [col, set] of state.columnFilters) {
    if (!(set instanceof Set)) continue;
    const label = COL_FILTER_LABELS[col] || col;
    const text = set.size === 0
      ? `${label}: (none)`
      : set.size <= 2
        ? `${label}: ${[...set].map((v) => v === "" ? "(blank)" : v).join(", ")}`
        : `${label}: ${set.size} values`;
    const tag = document.createElement("span");
    tag.className = "filter-tag";
    tag.textContent = text + " ";
    const x = document.createElement("button");
    x.type = "button";
    x.textContent = "×";
    x.title = `Clear ${label} filter`;
    x.addEventListener("click", () => {
      state.columnFilters.delete(col);
      applyFilters();
    });
    tag.appendChild(x);
    bar.appendChild(tag);
  }
}

// ============================================================ COLUMNS DROPDOWN

function loadColVisibility() {
  let saved = {};
  try {
    const raw = localStorage.getItem(COLS_STORAGE_KEY);
    if (raw) saved = JSON.parse(raw) || {};
  } catch { /* localStorage may be unavailable */ }
  for (const c of TOGGLEABLE_COLS) {
    state.colVisibility[c.key] = (c.key in saved) ? !!saved[c.key] : c.default;
  }
}

function saveColVisibility() {
  try {
    localStorage.setItem(COLS_STORAGE_KEY, JSON.stringify(state.colVisibility));
  } catch { /* ignore quota */ }
}

function applyColVisibility() {
  for (const c of TOGGLEABLE_COLS) {
    const on = state.colVisibility[c.key];
    for (const el of document.querySelectorAll(`th.col-${c.key}, td.col-${c.key}`)) {
      el.style.display = on ? "" : "none";
    }
  }
}

function buildColsMenu() {
  const menu = $("cols-menu");
  menu.replaceChildren();
  for (const c of TOGGLEABLE_COLS) {
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = state.colVisibility[c.key];
    cb.addEventListener("change", () => {
      state.colVisibility[c.key] = cb.checked;
      saveColVisibility();
      applyColVisibility();
    });
    const span = document.createElement("span");
    span.textContent = c.label;
    label.append(cb, span);
    menu.appendChild(label);
  }
}

// ============================================================ COUNTIES PICKER

function buildCountiesPicker() {
  const list = $("counties-list");
  list.replaceChildren();
  for (const county of KNOWN_COUNTIES) {
    const li = document.createElement("li");
    li.id = `county-row-${county.slug}`;
    li.className = "county-row idle";
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = county.slug;
    cb.checked = state.selectedCounties.has(county.slug);
    cb.addEventListener("change", () => {
      if (cb.checked) state.selectedCounties.add(county.slug);
      else state.selectedCounties.delete(county.slug);
      refreshFromSelection();
    });
    const meta = document.createElement("span");
    meta.className = "county-meta";
    const name = document.createElement("span");
    name.className = "county-name";
    name.textContent = county.label;
    const sub = document.createElement("span");
    sub.className = "county-sub";
    sub.textContent = "not loaded";
    meta.append(name, sub);
    const status = document.createElement("span");
    status.className = "dl-status idle";
    status.setAttribute("aria-hidden", "true");
    label.append(cb, meta);
    li.append(status);
    li.appendChild(label);
    list.appendChild(li);
    const current = state.countyStatus.get(county.slug);
    if (current) setCountyStatus(county.slug, current.status, current.detail);
  }
  updateCountiesSummary();
}

function updateCountiesSummary() {
  const n = state.selectedCounties.size;
  const total = KNOWN_COUNTIES.length;
  const summary = $("counties-summary");
  const loaded = [...state.selectedCounties].filter((slug) => state.loadedCounties.has(slug)).length;
  if (n === 0) summary.textContent = "none";
  else if (n === total) summary.textContent = `all ${loaded}/${total}`;
  else if (n <= 2) {
    summary.textContent = [...state.selectedCounties]
      .map((s) => COUNTY_LABEL[s] || s).join(", ");
  } else {
    summary.textContent = `${n} selected`;
  }
  const dlBtn = $("dl-btn");
  if (dlBtn) {
    const label = n === 0
      ? "Database downloads, no counties selected"
      : n === total
        ? `Database downloads, all ${total} counties selected, ${loaded} loaded`
        : `Database downloads, ${n} counties selected, ${loaded} loaded`;
    dlBtn.setAttribute("aria-label", label);
  }
}

function refreshFromSelection() {
  updateCountiesSummary();
  void ensureCountiesLoaded();
}

function retryFailedCounties() {
  for (const slug of state.selectedCounties) {
    if (state.countyStatus.get(slug)?.status === "error") {
      setCountyStatus(slug, "idle", "waiting to retry...");
    }
  }
  void ensureCountiesLoaded({ retryErrors: true });
}

// ============================================================ CSV EXPORT

function exportCsv() {
  const rows = state.filtered;
  if (!rows.length) {
    window.alert("No rulings to export.");
    return;
  }
  const cols = [
    "id", "county", "dept", "hearing_date", "case_number", "case_title",
    "motion_type", "outcome", "conditional", "continued_to", "outcome_text",
    "page_start", "page_end", "source_url",
  ];
  const header = cols.map(csvCell).join(",");
  const lines = [header];
  for (const r of rows) {
    const out = {
      id: r._shortId,
      county: COUNTY_LABEL[r.county] || r.county,
      dept: r.dept,
      hearing_date: r.hearing_date,
      case_number: r.case_number,
      case_title: r.case_title,
      motion_type: r.motion_type,
      outcome: r.outcome,
      conditional: r.conditional ? "true" : "false",
      continued_to: r.continued_to || "",
      outcome_text: r.outcome_text,
      page_start: r.page_start,
      page_end: r.page_end,
      source_url: r.source_url,
    };
    lines.push(cols.map((c) => csvCell(out[c])).join(","));
  }
  const csv = lines.join("\r\n");
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const stamp = new Date().toISOString().slice(0, 10);
  const a = document.createElement("a");
  a.href = url;
  a.download = `tentatives-${stamp}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  let s = String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

// ============================================================ URL SYNC

function syncUrl() {
  const params = new URLSearchParams();
  if (state.selectedCounties.size > 0) {
    const all = KNOWN_COUNTIES.length;
    if (state.selectedCounties.size === all) params.set("counties", "all");
    else params.set("counties", [...state.selectedCounties].sort().join(","));
  }
  for (const k of FILTER_IDS) {
    const v = state.filters[k];
    if (v) params.set(k, v);
  }
  for (const [col, set] of state.columnFilters) {
    if (set instanceof Set && set.size > 0) {
      params.set(`cf_${col}`, [...set].join("|"));
    }
  }
  if (
    SORT_COLUMNS.has(state.sort.col) &&
    SORT_DIRECTIONS.has(state.sort.dir) &&
    (state.sort.col !== "hearing_date" || state.sort.dir !== "desc")
  ) {
    params.set("sort", `${state.sort.col}:${state.sort.dir}`);
  }
  if (state.page !== 1) params.set("page", String(state.page));
  if (state.pageSize !== 100) params.set("rows", String(state.pageSize));
  if (state.viewMode === "dossier") params.set("view", "dossier");
  if (state.selectedRowId) params.set("sel", state.selectedRowId);
  // Preserve ?r=<id> if a modal is open.
  const current = new URLSearchParams(window.location.search);
  if (current.get("r")) params.set("r", current.get("r"));
  const qs = params.toString();
  const newUrl = qs ? `?${qs}` : window.location.pathname;
  window.history.replaceState(null, "", newUrl);
}

function addCountyFromShortId(id) {
  if (!id || state.selectedCounties.size > 0) return;
  const code = String(id).split("-")[0];
  const slug = COUNTY_BY_CODE[code];
  if (slug) state.selectedCounties.add(slug);
}

function readUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const k of FILTER_IDS) {
    if (params.has(k)) state.filters[k] = params.get(k);
  }
  for (const [name, value] of params) {
    if (!name.startsWith("cf_")) continue;
    const col = name.slice(3);
    // Only restore filters for columns that actually support filtering; an
    // unknown cf_ param would otherwise match nothing and blank the table.
    if (!value || !(col in COL_FILTER_LABELS)) continue;
    state.columnFilters.set(col, new Set(value.split("|")));
  }
  const sort = params.get("sort");
  if (sort) {
    const [col, dir] = sort.split(":");
    if (SORT_COLUMNS.has(col) && SORT_DIRECTIONS.has(dir)) {
      state.sort = { col, dir };
    }
  }
  const page = Number(params.get("page"));
  if (Number.isInteger(page) && page > 0) state.page = page;
  const rows = Number(params.get("rows"));
  if ([50, 100, 250, 500].includes(rows)) state.pageSize = rows;
  const counties = params.get("counties");
  if (counties) {
    const known = new Set(KNOWN_COUNTIES.map((c) => c.slug));
    if (counties === "all") {
      for (const c of known) state.selectedCounties.add(c);
    } else {
      for (const slug of counties.split(",")) {
        if (known.has(slug)) state.selectedCounties.add(slug);
      }
    }
  }
  const view = params.get("view");
  if (view === "dossier" || view === "table") {
    state.viewMode = view;
    try { localStorage.setItem(VIEW_MODE_STORAGE_KEY, state.viewMode); } catch { /* ignore */ }
  }
  const sel = params.get("sel");
  if (sel) {
    state.selectedRowId = sel;
    addCountyFromShortId(sel);
  }
  const r = params.get("r");
  if (r) {
    state.pendingFocusId = r;
    // If user landed on a ruling permalink without a county selection,
    // load the county encoded in the ID so the row resolves.
    addCountyFromShortId(r);
  }
}

function pushFiltersToUI() {
  for (const k of FILTER_IDS) {
    const el = $(k);
    if (el) el.value = state.filters[k];
  }
  const pageSize = $("page-size");
  if (pageSize) pageSize.value = String(state.pageSize);
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
    } else {
      el.addEventListener("change", updateFilter);
    }
  }

  $("reset").addEventListener("click", () => {
    for (const k of FILTER_IDS) state.filters[k] = "";
    state.columnFilters.clear();
    pushFiltersToUI();
    applyFilters();
  });

  $("counties-all").addEventListener("click", () => {
    for (const c of KNOWN_COUNTIES) state.selectedCounties.add(c.slug);
    for (const cb of $("counties-list").querySelectorAll("input[type=checkbox]")) cb.checked = true;
    refreshFromSelection();
  });
  $("counties-none").addEventListener("click", () => {
    state.selectedCounties.clear();
    for (const cb of $("counties-list").querySelectorAll("input[type=checkbox]")) cb.checked = false;
    refreshFromSelection();
  });

  $("dl-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    const menu = $("dl-menu");
    const wasOpen = menu.classList.contains("open");
    $("cols-menu").classList.remove("open");
    $("cols-btn").classList.remove("active");
    $("cols-btn").setAttribute("aria-expanded", "false");
    menu.classList.toggle("open", !wasOpen);
    $("dl-btn").classList.toggle("active", !wasOpen);
    $("dl-btn").setAttribute("aria-expanded", String(!wasOpen));
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#dl-menu") && !e.target.closest("#dl-btn")) {
      $("dl-menu").classList.remove("open");
      $("dl-btn").classList.remove("active");
      $("dl-btn").setAttribute("aria-expanded", "false");
    }
  });

  $("permalink").addEventListener("click", async () => {
    syncUrl();
    const ok = await copyText(window.location.href);
    if (ok) flashCopied($("permalink"), "Copy link");
    else window.alert(window.location.href);
  });

  for (const th of document.querySelectorAll("thead th.sortable")) {
    th.addEventListener("click", (e) => {
      // Ignore clicks on the filter button; that opens the popup, not sort.
      if (e.target.closest(".col-filter-btn")) return;
      const col = th.dataset.col;
      if (!SORT_COLUMNS.has(col)) return;
      if (state.sort.col === col) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort.col = col;
        state.sort.dir = col === "hearing_date" ? "desc" : "asc";
      }
      applyFilters();
    });
  }

  // One delegated click handler for the table body: share button vs. PDF
  // link vs. case history vs. row selection/detail.
  $("results-body").addEventListener("click", async (e) => {
    const share = e.target.closest("button[data-share]");
    if (share) {
      e.stopPropagation();
      const tr = e.target.closest("tr[data-idx]");
      if (!tr) return;
      const row = state.filtered[Number(tr.dataset.idx)];
      const url = modalUrlFor(row || tr.dataset.id);
      const ok = await copyText(url);
      if (ok) {
        share.classList.add("copied");
        const orig = share.textContent;
        share.textContent = "OK";
        setTimeout(() => {
          share.classList.remove("copied");
          share.textContent = orig;
        }, 1100);
      } else {
        window.alert(url);
      }
      return;
    }
    const title = e.target.closest(".case-title-link");
    if (title) {
      e.stopPropagation();
      const rowEl = e.target.closest("tr[data-idx]");
      const row = rowEl ? state.filtered[Number(rowEl.dataset.idx)] : null;
      openCaseHistory(title.dataset.cn, row);
      return;
    }
    if (e.target.closest("a")) return; // PDF link, let it through
    const row = e.target.closest("tr[data-idx]");
    if (!row) return;
    selectRuling(state.filtered[Number(row.dataset.idx)], Number(row.dataset.idx));
  });

  // Column filter buttons. Delegated since the table re-renders.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".col-filter-btn");
    if (btn) {
      e.stopPropagation();
      const col = btn.dataset.filterCol;
      if (_openColFilter === col) { closeColFilter(); return; }
      openColFilter(col, btn);
      return;
    }
    if (_openColFilter && !e.target.closest("#col-filter-pop")) {
      closeColFilter();
    }
  });

  // Modal controls.
  $("modal-close").addEventListener("click", closeModal);
  $("overlay").addEventListener("click", (e) => {
    if (e.target === $("overlay")) closeModal();
  });
  $("case-close").addEventListener("click", closeCaseHistory);
  $("case-overlay").addEventListener("click", (e) => {
    if (e.target === $("case-overlay")) closeCaseHistory();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (_openColFilter) closeColFilter();
      else if ($("case-overlay").classList.contains("open")) closeCaseHistory();
      else closeModal();
    }
  });
  $("modal-share").addEventListener("click", async () => {
    const shareBtn = $("modal-share");
    const id = shareBtn.dataset.id;
    if (!id) return;
    const url = modalUrlFor(id, shareBtn.dataset.county || "");
    const ok = await copyText(url);
    if (ok) flashCopied($("modal-share"), "Copy link");
    else window.alert(url);
  });

  // Pager.
  $("prev-page").addEventListener("click", () => { state.page--; render(); syncUrl(); });
  $("next-page").addEventListener("click", () => { state.page++; render(); syncUrl(); });
  $("page-size").addEventListener("change", (e) => {
    state.pageSize = Number(e.target.value);
    state.page = 1;
    render();
    syncUrl();
  });

  for (const btn of document.querySelectorAll("[data-view-mode]")) {
    btn.addEventListener("click", () => setViewMode(btn.dataset.viewMode));
  }

  // Columns dropdown.
  $("cols-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    const menu = $("cols-menu");
    const wasOpen = menu.classList.contains("open");
    $("dl-menu").classList.remove("open");
    $("dl-btn").classList.remove("active");
    $("dl-btn").setAttribute("aria-expanded", "false");
    menu.classList.toggle("open", !wasOpen);
    $("cols-btn").classList.toggle("active", !wasOpen);
    $("cols-btn").setAttribute("aria-expanded", String(!wasOpen));
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#cols-menu") && !e.target.closest("#cols-btn")) {
      $("cols-menu").classList.remove("open");
      $("cols-btn").classList.remove("active");
      $("cols-btn").setAttribute("aria-expanded", "false");
    }
  });

  $("export-btn").addEventListener("click", exportCsv);
  $("county-load-retry").addEventListener("click", retryFailedCounties);
}

// ============================================================ BOOT

(async () => {
  try {
    await loadCountyManifest();
    loadColVisibility();
    readUrl();
    pushFiltersToUI();
    buildCountiesPicker();
    buildColsMenu();
    wire();
    $("loading-banner").hidden = true;
    $("loading-banner").setAttribute("aria-busy", "false");
    $("view-strip").hidden = false;
    $("toolbar").hidden = false;
    $("result-bar").hidden = false;
    $("results-wrap").hidden = false;
    applyFilters();
    if (state.selectedCounties.size > 0) {
      await ensureCountiesLoaded();
    }

    // Honour ?r=<id>: open the modal for that ruling once data is loaded.
    if (state.pendingFocusId) {
      const r = findRowById(state.pendingFocusId);
      if (r) openModal(r);
      state.pendingFocusId = null;
    }
  } catch (e) {
    console.error(e);
    $("loading-msg").textContent = "The database viewer could not start";
    $("loading-detail").textContent = e.message || String(e);
    $("loading-banner").classList.add("err");
    $("loading-banner").setAttribute("aria-busy", "false");
    $("loading-retry").hidden = false;
    $("loading-retry").addEventListener("click", () => window.location.reload());
  }
})();
