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
  const status = document.getElementById("status");
  status.textContent = "✓ saved";
  status.className = "ok";
  setTimeout(() => {
    status.textContent = "";
  }, 1800);
}

document.getElementById("save").addEventListener("click", save);
load();
