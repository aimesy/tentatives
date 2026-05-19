const FIELDS = [
  ["token", "githubToken"],
  ["owner", "githubOwner"],
  ["repo",  "githubRepo"],
  ["branch", "githubBranch"],
];

const DEFAULT_DELAY_SECONDS = 5;

const $ = (id) => document.getElementById(id);

async function load() {
  const keys = FIELDS.map(([, k]) => k).concat(["pageLoadDelayMs"]);
  const stored = await chrome.storage.local.get(keys);
  for (const [id, key] of FIELDS) {
    $(id).value = stored[key] || "";
  }
  const ms = Number.isFinite(+stored.pageLoadDelayMs) ? +stored.pageLoadDelayMs : DEFAULT_DELAY_SECONDS * 1000;
  $("delay").value = (ms / 1000).toString();
}

async function save(event) {
  if (event) event.preventDefault();
  const update = {};
  for (const [id, key] of FIELDS) {
    update[key] = $(id).value.trim();
  }
  const raw = $("delay").value.trim();
  const seconds = raw === "" ? DEFAULT_DELAY_SECONDS : Number(raw);
  if (!Number.isFinite(seconds) || seconds < 0) {
    setStatus("delay must be a non-negative number of seconds.", "err");
    return;
  }
  update.pageLoadDelayMs = Math.round(seconds * 1000);
  await chrome.storage.local.set(update);
  setStatus("Saved.", "ok");
}

function setStatus(text, cls = "") {
  const el = $("status");
  el.textContent = text;
  el.className = `status ${cls}`.trim();
}

async function testConnection() {
  const token = $("token").value.trim();
  const owner = $("owner").value.trim();
  const repo  = $("repo").value.trim();
  if (!token || !owner || !repo) {
    setStatus("Fill in PAT, owner, and repo first.", "err");
    return;
  }
  setStatus("Testing…");
  try {
    const r = await fetch(`https://api.github.com/repos/${owner}/${repo}`, {
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
      },
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      setStatus(`${r.status}: ${body.message || r.statusText}`, "err");
      return;
    }
    const canWrite = body.permissions?.push === true;
    if (!canWrite) {
      setStatus(
        `Read-only. PAT can read ${owner}/${repo} but not write — add Contents: Read & Write.`,
        "err",
      );
      return;
    }
    setStatus(`Connected to ${owner}/${repo} (default branch: ${body.default_branch}).`, "ok");
  } catch (e) {
    setStatus(`${e.message || e}`, "err");
  }
}

$("settings-form").addEventListener("submit", save);
$("test").addEventListener("click", testConnection);

$("reveal-token").addEventListener("click", () => {
  const input = $("token");
  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  $("reveal-token").textContent = showing ? "Show" : "Hide";
});

load();
