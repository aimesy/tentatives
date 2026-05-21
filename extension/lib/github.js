// Minimal GitHub API client for contents reads/writes and Git Data commits.

const API = "https://api.github.com";
const DEFAULT_MAX_ATTEMPTS = 5;
const RETRY_BASE_MS = 1000;
const RETRY_MAX_MS = 30000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryAfterMs(headers) {
  const raw = headers.get("Retry-After");
  if (!raw) return null;
  const seconds = Number(raw);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const dateMs = Date.parse(raw);
  if (Number.isFinite(dateMs)) return Math.max(0, dateMs - Date.now());
  return null;
}

function rateLimitResetMs(headers) {
  const remaining = headers.get("X-RateLimit-Remaining");
  const reset = Number(headers.get("X-RateLimit-Reset"));
  if (remaining !== "0" || !Number.isFinite(reset)) return null;
  return Math.max(0, reset * 1000 - Date.now());
}

function bodyMessage(body, fallback = "") {
  if (body && typeof body === "object" && body.message) return String(body.message);
  return String(body || fallback || "");
}

function isRetryableStatus(status, body, headers) {
  if (status === 429 || status >= 500) return true;
  if (status !== 403) return false;
  if (retryAfterMs(headers) !== null || rateLimitResetMs(headers) !== null) return true;
  const msg = bodyMessage(body).toLowerCase();
  return msg.includes("secondary rate limit")
    || msg.includes("rate limit exceeded")
    || msg.includes("abuse detection");
}

function retryDelayMs(attempt, headers) {
  const fromHeader = retryAfterMs(headers) ?? rateLimitResetMs(headers);
  if (fromHeader !== null) return Math.min(RETRY_MAX_MS, fromHeader);
  const exponential = RETRY_BASE_MS * (2 ** Math.max(0, attempt - 1));
  const jitter = Math.floor(Math.random() * 250);
  return Math.min(RETRY_MAX_MS, exponential + jitter);
}

export function base64ToText(base64) {
  const binary = atob(String(base64 || "").replace(/\s/g, ""));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
}

function textToBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function encodeRefPath(ref) {
  return String(ref || "").split("/").map(encodeURIComponent).join("/");
}

async function gh(path, token, init = {}) {
  const maxAttempts = init.maxAttempts || DEFAULT_MAX_ATTEMPTS;
  const requestInit = { ...init };
  delete requestInit.maxAttempts;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    let r;
    try {
      r = await fetch(`${API}${path}`, {
        ...requestInit,
        headers: {
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          Authorization: `Bearer ${token}`,
          ...(requestInit.headers || {}),
        },
      });
    } catch (e) {
      if (attempt >= maxAttempts) throw e;
      await sleep(Math.min(RETRY_MAX_MS, RETRY_BASE_MS * (2 ** (attempt - 1))));
      continue;
    }

    const text = await r.text();
    let body;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text;
    }
    if (r.ok) return body;

    if (attempt < maxAttempts && isRetryableStatus(r.status, body, r.headers)) {
      await sleep(retryDelayMs(attempt, r.headers));
      continue;
    }

    const msg = bodyMessage(body, text || r.statusText);
    const err = new Error(`GitHub ${r.status}: ${msg}`);
    err.status = r.status;
    err.body = body;
    err.retryAfterMs = retryAfterMs(r.headers);
    throw err;
  }
  throw new Error("GitHub request failed after retries");
}

export async function fileExists({ owner, repo, branch, path, token }) {
  const ref = branch ? `?ref=${encodeURIComponent(branch)}` : "";
  try {
    await gh(`/repos/${owner}/${repo}/contents/${path}${ref}`, token, {
      method: "GET",
    });
    return true;
  } catch (e) {
    if (e.status === 404) return false;
    throw e;
  }
}

export async function putFile({
  owner,
  repo,
  branch,
  path,
  message,
  contentBase64,
  token,
}) {
  return gh(`/repos/${owner}/${repo}/contents/${path}`, token, {
    method: "PUT",
    body: JSON.stringify({
      message,
      content: contentBase64,
      ...(branch ? { branch } : {}),
    }),
  });
}

export async function getFile({ owner, repo, branch, path, token }) {
  // Cache-busting timestamp so the CDN doesn't hand back a stale copy right
  // after a write (GitHub's Contents API is eventually consistent).
  const params = new URLSearchParams();
  if (branch) params.set("ref", branch);
  params.set("_", Date.now().toString());
  return gh(`/repos/${owner}/${repo}/contents/${path}?${params}`, token, {
    method: "GET",
    headers: { "Cache-Control": "no-cache" },
  });
}

export async function appendNdjsonLine({
  owner,
  repo,
  branch,
  path,
  newLine,
  message,
  token,
  maxAttempts = 5,
}) {
  return appendNdjsonLines({
    owner,
    repo,
    branch,
    path,
    newLines: [newLine],
    message,
    token,
    maxAttempts,
  });
}

export async function appendNdjsonLines({
  owner,
  repo,
  branch,
  path,
  newLines,
  message,
  token,
  maxAttempts = 5,
}) {
  const lines = (newLines || []).filter((line) => String(line || "").trim());
  if (lines.length === 0) return null;

  // Fetch current content (if any), append a line, PUT back with sha as
  // optimistic concurrency. GitHub returns 409 if the sha is stale (eventual
  // consistency window after a recent write); retry with a fresh GET.
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    let existing;
    try {
      existing = await getFile({ owner, repo, branch, path, token });
    } catch (e) {
      if (e.status !== 404) throw e;
    }

    let content = "";
    let sha;
    if (existing) {
      content = base64ToText(existing.content);
      sha = existing.sha;
    }
    const updated = (content.endsWith("\n") || !content ? content : content + "\n")
      + lines.join("\n") + "\n";
    const updatedB64 = textToBase64(updated);

    try {
      return await gh(`/repos/${owner}/${repo}/contents/${path}`, token, {
        method: "PUT",
        body: JSON.stringify({
          message,
          content: updatedB64,
          ...(branch ? { branch } : {}),
          ...(sha ? { sha } : {}),
        }),
      });
    } catch (e) {
      if (e.status === 409 && attempt < maxAttempts) {
        // Stale sha - wait and retry with fresh state.
        await sleep(400 * attempt);
        continue;
      }
      throw e;
    }
  }
}

export async function appendNdjsonFileBatch({
  owner,
  repo,
  branch,
  files,
  message,
  token,
  maxAttempts = 5,
}) {
  const normalized = (files || [])
    .map((file) => ({
      path: file.path,
      newLines: (file.newLines || []).filter((line) => String(line || "").trim()),
    }))
    .filter((file) => file.path && file.newLines.length > 0);
  if (normalized.length === 0) return null;

  if (!branch) {
    let last = null;
    for (const file of normalized) {
      last = await appendNdjsonLines({
        owner,
        repo,
        branch,
        path: file.path,
        newLines: file.newLines,
        message,
        token,
        maxAttempts,
      });
    }
    return last;
  }

  const refPath = encodeRefPath(`heads/${branch}`);
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const ref = await gh(`/repos/${owner}/${repo}/git/ref/${refPath}`, token, {
      method: "GET",
    });
    const headSha = ref.object.sha;
    const headCommit = await gh(`/repos/${owner}/${repo}/git/commits/${headSha}`, token, {
      method: "GET",
    });

    const tree = [];
    for (const file of normalized) {
      let existing;
      try {
        existing = await getFile({ owner, repo, branch, path: file.path, token });
      } catch (e) {
        if (e.status !== 404) throw e;
      }
      const current = existing ? base64ToText(existing.content) : "";
      const updated = (current.endsWith("\n") || !current ? current : current + "\n")
        + file.newLines.join("\n") + "\n";
      tree.push({
        path: file.path,
        mode: "100644",
        type: "blob",
        content: updated,
      });
    }

    const newTree = await gh(`/repos/${owner}/${repo}/git/trees`, token, {
      method: "POST",
      body: JSON.stringify({
        base_tree: headCommit.tree.sha,
        tree,
      }),
    });
    const commit = await gh(`/repos/${owner}/${repo}/git/commits`, token, {
      method: "POST",
      body: JSON.stringify({
        message,
        tree: newTree.sha,
        parents: [headSha],
      }),
    });

    try {
      await gh(`/repos/${owner}/${repo}/git/refs/${refPath}`, token, {
        method: "PATCH",
        body: JSON.stringify({
          sha: commit.sha,
          force: false,
        }),
      });
      return commit;
    } catch (e) {
      if ((e.status === 409 || e.status === 422) && attempt < maxAttempts) {
        await sleep(Math.min(RETRY_MAX_MS, 500 * attempt));
        continue;
      }
      throw e;
    }
  }
  throw new Error("GitHub batch append failed after retries");
}
