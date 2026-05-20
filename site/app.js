// California Tentative Rulings - static viewer.
//
// Reads data/<county>/rulings.parquet from the same origin via hyparquet,
// merges everything into one in-memory array, and drives a filter/sort/page
// view. All filtering happens client-side.

// hyparquet ships as a single ES module; load from the official CDN. Pinned
// version so a breaking minor doesn't surprise the deployed site.
const { asyncBufferFromUrl, parquetReadObjects } = await import(
  "https://cdn.jsdelivr.net/npm/hyparquet@1.18.0/src/hyparquet.min.js"
);

// Counties we know about. Any whose parquet 404s is skipped silently - the
// page works fine with whatever subset is published.
const KNOWN_COUNTIES = [
  { slug: "el-dorado",    label: "El Dorado" },
  { slug: "contra-costa", label: "Contra Costa" },
  { slug: "placer",       label: "Placer" },
];

const COUNTY_LABEL = Object.fromEntries(KNOWN_COUNTIES.map((c) => [c.slug, c.label]));

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
    row.innerHTML = `<span class="s-name">${name}</span><span class="s-val"></span>`;
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

async function resolveDataRoot() {
  if (resolvedDataRoot) return resolvedDataRoot;
  for (const root of DATA_ROOT_CANDIDATES) {
    for (const county of KNOWN_COUNTIES) {
      try {
        const r = await fetch(`${root}/${county.slug}/rulings.parquet`, { method: "HEAD" });
        if (r.ok) {
          resolvedDataRoot = root;
          return root;
        }
      } catch { /* ignore network errors per candidate */ }
    }
  }
  // No data found at either layout. Default to production so the per-county
  // 404 stages render correctly.
  resolvedDataRoot = DATA_ROOT_CANDIDATES[0];
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
  // asyncBufferFromUrl lets hyparquet do range requests; for our small (<1MB)
  // parquets this is mostly equivalent to slurping the whole thing, but is
  // future-proof if a county's file grows.
  const file = await asyncBufferFromUrl({ url });
  setStage(county.label, "parsing...", "active");
  const rows = await parquetReadObjects({ file });
  setStage(county.label, `${rows.length.toLocaleString()} rulings`, "done");
  return rows;
}

async function loadAll() {
  setStage("Discover", "checking county parquets", "active");
  let total = 0;
  for (const county of KNOWN_COUNTIES) {
    try {
      const rows = await fetchAndParse(county);
      for (const r of rows) {
        // Normalize: hearing_date stored as string ISO; keep as-is for sort.
        state.rows.push(r);
      }
      total += rows.length;
    } catch (e) {
      console.error(`Failed to load ${county.slug}:`, e);
      setStage(county.label, `error: ${e.message || e}`, "err");
    }
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
    const blob = [
      r.case_number, r.case_title, r.motion_type,
      r.outcome_text, r.body_text, r.full_text,
    ].filter(Boolean).join(" ").toLowerCase();
    return blob.includes(needle);
  });

  // Sort.
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
  if (slice.length === 0) {
    body.innerHTML = `<tr><td colspan="8" class="empty">No rulings match the current filters.</td></tr>`;
  } else {
    body.innerHTML = slice.map((r, i) => renderRow(r, start + i)).join("");
  }

  // Header sort markers.
  for (const th of document.querySelectorAll("thead th[data-col]")) {
    const col = th.dataset.col;
    const marker = th.querySelector(".sort-marker");
    if (col === state.sort.col) {
      th.classList.add("sorted");
      marker.textContent = state.sort.dir === "asc" ? "↑" : "↓";
    } else {
      th.classList.remove("sorted");
      marker.textContent = "";
    }
  }

  $("stats").textContent =
    `${state.rows.length.toLocaleString()} rulings | ` +
    `${new Set(state.rows.map((r) => r.county)).size} counties`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function pdfHref(r) {
  if (!r.source_url) return null;
  const base = r.source_url.startsWith("http") ? r.source_url : null;
  if (!base) return null;
  return r.page_start ? `${base}#page=${r.page_start}` : base;
}

function renderRow(r, idx) {
  const outcomeClass = r.outcome || "other";
  const condBadge = r.conditional ? `<span class="cond" title="ABSENT OBJECTION -> granted">cond.</span>` : "";
  const pdf = pdfHref(r);
  const pdfCell = pdf
    ? `<a href="${escapeHtml(pdf)}" target="_blank" rel="noopener">PDF${r.page_start ? ` p.${r.page_start}` : ""}</a>`
    : "-";
  return `
    <tr data-idx="${idx}">
      <td>${escapeHtml(COUNTY_LABEL[r.county] || r.county || "")}</td>
      <td>${escapeHtml(r.dept || "")}</td>
      <td>${escapeHtml(r.hearing_date || "")}</td>
      <td class="case">${escapeHtml(r.case_number || "")}</td>
      <td class="title" title="${escapeHtml(r.case_title || "")}">${escapeHtml(r.case_title || "")}</td>
      <td>${escapeHtml(r.motion_type || "")}</td>
      <td class="outcome"><span class="outcome-pill ${outcomeClass}">${escapeHtml(r.outcome || "-")}</span>${condBadge}</td>
      <td>${pdfCell}</td>
    </tr>`;
}

// ============================================================ DRAWER

function openDrawer(idx) {
  const r = state.filtered[idx];
  if (!r) return;
  $("d-case").textContent = r.case_number || "(no case #)";
  $("d-title").textContent = r.case_title || "";
  const kv = $("d-kv");
  const rows = [
    ["County", COUNTY_LABEL[r.county] || r.county],
    ["Dept", r.dept],
    ["Division", r.division],
    ["Date", r.hearing_date],
    ["Motion", r.motion_type],
    ["Outcome", r.outcome + (r.conditional ? " (conditional)" : "")],
    ["Continued to", r.continued_to],
    ["Pages", r.page_start === r.page_end ? r.page_start : `${r.page_start}-${r.page_end}`],
    ["Source", r.source_url ? `<a href="${escapeHtml(r.source_url)}" target="_blank" rel="noopener">PDF</a>` : "-"],
    ["Parser", r.parser_version],
  ];
  kv.innerHTML = rows
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${k === "Source" ? v : escapeHtml(v)}</dd>`)
    .join("");
  $("d-outcome").textContent = r.outcome_text || "(empty)";
  $("d-full").textContent = r.full_text || r.body_text || "(empty)";
  $("drawer").classList.add("open");
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
  for (const [k, v] of Object.entries(state.filters)) {
    if (v) params.set(k, v);
  }
  if (state.sort.col !== "hearing_date" || state.sort.dir !== "desc") {
    params.set("sort", `${state.sort.col}:${state.sort.dir}`);
  }
  const qs = params.toString();
  const newUrl = qs ? `?${qs}` : window.location.pathname;
  window.history.replaceState(null, "", newUrl);
}

function readUrl() {
  const params = new URLSearchParams(window.location.search);
  for (const k of Object.keys(state.filters)) {
    if (params.has(k)) state.filters[k] = params.get(k);
  }
  const sort = params.get("sort");
  if (sort) {
    const [col, dir] = sort.split(":");
    if (col) state.sort.col = col;
    if (dir === "asc" || dir === "desc") state.sort.dir = dir;
  }
}

function pushFiltersToUI() {
  for (const k of Object.keys(state.filters)) {
    const el = $(k);
    if (el) el.value = state.filters[k];
  }
}

// ============================================================ WIRING

function wire() {
  for (const id of ["q", "county", "dept", "outcome", "from", "to"]) {
    const el = $(id);
    const evt = id === "q" ? "input" : "change";
    el.addEventListener(evt, () => {
      state.filters[id] = el.value;
      applyFilters();
    });
  }

  $("reset").addEventListener("click", () => {
    for (const k of Object.keys(state.filters)) state.filters[k] = "";
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
