# visibility: public
"""Preserve every capture record when concurrent append operations conflict.

Only capture provenance manifests may be resolved. Other conflicts fail so the
workflow's raw capture artifact can be recovered without choosing either side.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = re.compile(r"archive/[a-z0-9-]+/(?:page-)?captures\.ndjson\Z")


def merge_manifests(*snapshots: bytes) -> bytes:
    """Keep all fields and the largest existing multiplicity of each row."""
    kept: Counter[str] = Counter()
    lines: list[bytes] = []
    for snapshot in snapshots:
        present: Counter[str] = Counter()
        for line in snapshot.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not row.get("source_sha256") or not row.get("source_url"):
                raise ValueError("A capture manifest contains an invalid record")
            key = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            present[key] += 1
            if present[key] > kept[key]:
                lines.append(line)
                kept[key] += 1
    return b"\n".join(lines) + (b"\n" if lines else b"")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=check)


def resolve_current_conflicts() -> int:
    paths = [os.fsdecode(p) for p in git("diff", "--name-only", "--diff-filter=U", "-z").stdout.split(b"\0") if p]
    if not paths:
        raise RuntimeError("Rebase failed without capture manifest conflicts")
    if any(not MANIFEST.fullmatch(p) for p in paths):
        raise RuntimeError("Rebase includes a conflict outside capture manifests; use the preserved artifact")
    merged: dict[str, bytes] = {}
    for path in paths:
        snapshots = []
        for stage in (1, 2, 3):
            result = git("show", f":{stage}:{path}", check=False)
            if result.returncode and stage != 1:
                raise RuntimeError(f"Cannot read both capture manifests for {path}")
            snapshots.append(result.stdout if result.returncode == 0 else b"")
        merged[path] = merge_manifests(*snapshots)
    # Validate every manifest before writing any of them.
    for path, content in merged.items():
        (ROOT / path).write_bytes(content)
        git("add", "--", path)
    return len(paths)


def main() -> None:
    for _ in range(20):
        count = resolve_current_conflicts()
        print(f"Preserved concurrent records in {count} capture manifests")
        result = subprocess.run(["git", "rebase", "--continue"], cwd=ROOT, env={**os.environ, "GIT_EDITOR": "true"})
        if result.returncode == 0:
            return
    raise RuntimeError("Rebase exceeded the capture manifest resolution limit; use the preserved artifact")


if __name__ == "__main__":
    main()
