// Minimal GitHub Contents API client.
// One commit per file is fine for v1 (single-page captures of 1-20 PDFs).
// Switch to Git Data API later if we batch hundreds at a time (Wayback dumps).

const API = "https://api.github.com";

async function gh(path, token, init = {}) {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      Authorization: `Bearer ${token}`,
      ...(init.headers || {}),
    },
  });
  const text = await r.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!r.ok) {
    const msg = body && body.message ? body.message : text || r.statusText;
    const err = new Error(`GitHub ${r.status}: ${msg}`);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return body;
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
      content = atob(existing.content.replace(/\n/g, ""));
      sha = existing.sha;
    }
    const updated = (content.endsWith("\n") || !content ? content : content + "\n")
      + newLine + "\n";
    const updatedB64 = btoa(unescape(encodeURIComponent(updated)));

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
        // Stale sha — wait and retry with fresh state.
        await new Promise((r) => setTimeout(r, 400 * attempt));
        continue;
      }
      throw e;
    }
  }
}
