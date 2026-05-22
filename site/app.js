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
const FILTER_IDS = ["q", "dept", "outcome", "from", "to"];
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
    dept: "",
    outcome: "",
    from: "",
    to: "",
  },
  // Counties currently loaded into state.rows (slug -> rows[]). Used so we can
  // remove a county's rows when the user unticks it without re-fetching the
  // others. Default: empty - users opt in per county.
  loadedCounties: new Map(),
  selectedCounties: new Set(),
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
    // Published Parquet files are uncompressed so CSP can stay free of WASM/eval.
    parquetModulePromise = import("./vendor/hyparquet-1.18.1/src/index.js").then((parquet) => {
      setStage("Engine", "ready", "done");
      return parquet;
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
  let res;
  try {
    res = await fetch(url);
  } catch (e) {
    setStage(county.label, `network error: ${e.message || e}`, "err");
    return [];
  }
  if (res.status === 404) {
    setStage(county.label, "no data yet", "done");
    return [];
  }
  if (!res.ok) {
    setStage(county.label, `HTTP ${res.status}`, "err");
    return [];
  }
  // Fetch the full file rather than relying on HEAD + Range. GitHub Pages
  // applies transport encoding to .parquet, so a HEAD Content-Length can
  // disagree with the decoded body length, which makes hyparquet slice
  // the wrong bytes and fail with "footer != PAR1".
  const buffer = await res.arrayBuffer();
  const { parquetReadObjects } = await loadParquetModule();
  const file = {
    byteLength: buffer.byteLength,
    async slice(start, end) { return buffer.slice(start, end); },
  };
  setStage(county.label, "parsing...", "active");
  const rows = await parquetReadObjects({ file });
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

async function ensureCountiesLoaded() {
  const wanted = new Set(state.selectedCounties);
  const toAdd = [...wanted].filter((slug) => !state.loadedCounties.has(slug));
  const toRemove = [...state.loadedCounties.keys()].filter((slug) => !wanted.has(slug));

  for (const slug of toRemove) {
    state.loadedCounties.delete(slug);
    const stage = $(`stage-${COUNTY_LABEL[slug] || slug}`);
    if (stage) stage.remove();
  }

  const batches = await Promise.all(toAdd.map(async (slug) => {
    const county = KNOWN_COUNTIES.find((c) => c.slug === slug);
    if (!county) return [slug, []];
    try {
      const rows = await fetchAndParse(county);
      return [slug, rows.map(normalizeRow)];
    } catch (e) {
      console.error(`Failed to load ${slug}:`, e);
      setStage(county.label, `error: ${e.message || e}`, "err");
      return [slug, []];
    }
  }));
  for (const [slug, rows] of batches) state.loadedCounties.set(slug, rows);

  state.rows = [];
  for (const rows of state.loadedCounties.values()) state.rows.push(...rows);
}

// ============================================================ FILTER & SORT

function applyFilters() {
  const { q, dept, outcome, from, to } = state.filters;
  const needle = q.trim().toLowerCase();

  state.filtered = state.rows.filter((r) => {
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
    cell.colSpan = 9;
    cell.className = "empty";
    cell.textContent = state.selectedCounties.size === 0
      ? "Pick one or more counties above to load rulings."
      : "No rulings match the current filters.";
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

  if (state.rows.length === 0) {
    $("stats").textContent = state.selectedCounties.size === 0
      ? "no counties selected"
      : "loading...";
  } else {
    $("stats").textContent =
      `${state.rows.length.toLocaleString()} rulings | ` +
      `${new Set(state.rows.map((r) => r.county)).size} counties`;
  }
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
  const countyCell = appendCell(row, COUNTY_LABEL[r.county] || r.county || "", "col-county");
  countyCell.title = COUNTY_LABEL[r.county] || r.county || "";
  appendCell(row, r.dept || "", "col-dept");
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

  const previewText = (r.outcome_text || r.body_text || r.full_text || "").trim();
  const textCell = appendCell(row, previewText, "text-preview");
  if (previewText) textCell.title = previewText.slice(0, 600);

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
  const depts = new Set();
  const outcomes = new Set();
  for (const r of state.rows) {
    if (r.dept)    depts.add(String(r.dept));
    if (r.outcome) outcomes.add(r.outcome);
  }
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
    opt.textContent = current;
    sel.appendChild(opt);
  }
  for (const { v, t } of items) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = t;
    sel.appendChild(opt);
  }
}

// ============================================================ COUNTIES PICKER

function buildCountiesPicker() {
  const list = $("counties-list");
  list.replaceChildren();
  for (const county of KNOWN_COUNTIES) {
    const li = document.createElement("li");
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
    const text = document.createElement("span");
    text.textContent = county.label;
    label.append(cb, text);
    li.appendChild(label);
    list.appendChild(li);
  }
  updateCountiesSummary();
}

function updateCountiesSummary() {
  const n = state.selectedCounties.size;
  const total = KNOWN_COUNTIES.length;
  const summary = $("counties-summary");
  if (n === 0) summary.textContent = "none";
  else if (n === total) summary.textContent = "all";
  else if (n <= 2) {
    summary.textContent = [...state.selectedCounties]
      .map((s) => COUNTY_LABEL[s] || s).join(", ");
  } else {
    summary.textContent = `${n} selected`;
  }
}

async function refreshFromSelection() {
  updateCountiesSummary();
  await ensureCountiesLoaded();
  populateFilters();
  applyFilters();
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
  try {
    await loadCountyManifest();
    readUrl();
    pushFiltersToUI();
    buildCountiesPicker();
    wire();
    if (state.selectedCounties.size > 0) {
      await ensureCountiesLoaded();
      populateFilters();
      pushFiltersToUI();
    }
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
