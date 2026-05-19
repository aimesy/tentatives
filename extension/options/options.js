const FIELDS = [
  ["token", "githubToken"],
  ["owner", "githubOwner"],
  ["repo", "githubRepo"],
  ["branch", "githubBranch"],
];

async function load() {
  const keys = FIELDS.map(([, k]) => k);
  const stored = await chrome.storage.local.get(keys);
  for (const [id, key] of FIELDS) {
    document.getElementById(id).value = stored[key] || "";
  }
}

async function save() {
  const update = {};
  for (const [id, key] of FIELDS) {
    update[key] = document.getElementById(id).value.trim();
  }
  await chrome.storage.local.set(update);
  setStatus("✓ saved", "ok");
}

function setStatus(text, cls = "") {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = cls;
}

async function testConnection() {
  const token = document.getElementById("token").value.trim();
  const owner = document.getElementById("owner").value.trim();
  const repo = document.getElementById("repo").value.trim();
  if (!token || !owner || !repo) {
    setStatus("Fill in PAT, owner, and repo first.", "err");
    return;
  }
  setStatus("Testing…");
  try {
    // Probe the repo metadata — succeeds if PAT can read it.
    const r = await fetch(`https://api.github.com/repos/${owner}/${repo}`, {
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
      },
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      setStatus(`✗ ${r.status}: ${body.message || r.statusText}`, "err");
      return;
    }
    // Check write permission. The repo response includes `permissions` when
    // authenticated as a collaborator/owner; absent on read-only PATs.
    const canWrite = body.permissions?.push === true;
    if (!canWrite) {
      setStatus(
        `Connected (read-only). PAT can read ${owner}/${repo} but not write — add "Contents: Read and write".`,
        "err",
      );
      return;
    }
    setStatus(`✓ connected to ${owner}/${repo} (default branch: ${body.default_branch})`, "ok");
  } catch (e) {
    setStatus(`✗ ${e.message || e}`, "err");
  }
}

document.getElementById("save").addEventListener("click", save);
document.getElementById("test").addEventListener("click", testConnection);
load();
