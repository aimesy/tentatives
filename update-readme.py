#!/usr/bin/env python3
"""Refresh the README LIVE block from normalized tentative-ruling data."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import urllib.request
from pathlib import Path, PurePosixPath

import pyarrow.parquet as pq


HERE = Path(__file__).parent
README = HERE / "README.md"
LIVE = HERE / "LIVE.md"
DATA_DIR = HERE / "data"
ARCHIVE_DIR = HERE / "archive"

LIVE_START = "<!-- tentatives-live:start -->"
LIVE_END = "<!-- tentatives-live:end -->"


def refresh_site_counties() -> None:
    script = HERE / "update-site-counties.py"
    spec = importlib.util.spec_from_file_location("update_site_counties", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_mb(value: int) -> str:
    return f"{value / (1024 * 1024):,.0f}"


def tracked_archive_sizes() -> dict[str, int] | None:
    """Archive file sizes at HEAD, in a sparse checkout.

    A sparse checkout (the courtproj harvest) holds only part of archive/ on
    disk, so counting files on disk would shrink the LIVE table. Its clone has
    no blobs either, and `git ls-tree -l` would fetch every one of them to read
    its size, so the sizes come from GitHub's tree API, one county subtree at a
    time (GITHUB_TOKEN for a private repository). Returns None for a full
    checkout, where the files on disk are the archive.
    """
    try:
        sparse = subprocess.run(
            ["git", "config", "--bool", "core.sparseCheckout"],
            cwd=HERE, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None
    if sparse.stdout.strip().lower() != "true":
        return None
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=HERE, capture_output=True, text=True, check=True,
    ).stdout.strip()
    repo = remote.split("github.com/", 1)[1].removesuffix(".git").strip("/")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "tentatives-update-readme"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    def tree(sha: str, recursive: bool) -> dict:
        url = f"https://api.github.com/repos/{repo}/git/trees/{sha}" + ("?recursive=1" if recursive else "")
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
            return json.load(response)

    def walk(sha: str, prefix: str, sizes: dict[str, int]) -> None:
        listing = tree(sha, recursive=True)
        if not listing.get("truncated"):
            for entry in listing["tree"]:
                if entry["type"] == "blob":
                    sizes[f"{prefix}/{entry['path']}"] = int(entry["size"])
            return
        for entry in tree(sha, recursive=False)["tree"]:
            if entry["type"] == "blob":
                sizes[f"{prefix}/{entry['path']}"] = int(entry["size"])
            elif entry["type"] == "tree":
                walk(entry["sha"], f"{prefix}/{entry['path']}", sizes)

    sizes: dict[str, int] = {}
    # Tree objects are in the clone, so listing the county subtrees is local.
    listing = subprocess.run(
        ["git", "ls-tree", "HEAD", "archive/"], cwd=HERE, capture_output=True, text=True, check=True,
    ).stdout
    for line in listing.splitlines():
        meta, path = line.split("	", 1)
        kind, sha = meta.split()[1:3]
        if kind == "tree":
            walk(sha, path, sizes)
    return sizes


def archive_file_stats() -> tuple[int, int]:
    count = 0
    size = 0
    tracked = tracked_archive_sizes()
    if tracked is not None:
        # Files written since HEAD (new captures, slices, OCR sidecars) count
        # from disk, the rest from the tree, as a full checkout would see them.
        files = dict(tracked)
        if ARCHIVE_DIR.exists():
            for path in ARCHIVE_DIR.rglob("*"):
                if path.is_file():
                    files[path.relative_to(HERE).as_posix()] = path.stat().st_size
        for rel, length in files.items():
            if PurePosixPath(rel).suffix.lower() in {".ndjson", ".json"}:
                continue
            count += 1
            size += length
        return count, size
    if not ARCHIVE_DIR.exists():
        return count, size
    for path in ARCHIVE_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".ndjson", ".json"}:
            continue
        count += 1
        size += path.stat().st_size
    return count, size


def live_stats() -> dict[str, int | str]:
    rulings = 0
    source_hashes: set[str] = set()
    first_dates: list[str] = []
    latest_dates: list[str] = []
    parsed_counties = 0

    for path in sorted(DATA_DIR.glob("*/rulings.parquet")):
        parsed_counties += 1
        meta = pq.read_metadata(path)
        rulings += int(meta.num_rows or 0)
        schema = pq.read_schema(path)
        columns = [name for name in ("source_sha256", "hearing_date") if name in schema.names]
        if not columns:
            continue
        table = pq.read_table(path, columns=columns)
        if "source_sha256" in table.column_names:
            source_hashes.update(
                value.as_py()
                for value in table["source_sha256"]
                if value.as_py()
            )
        if "hearing_date" in table.column_names:
            dates = sorted(
                value.as_py()
                for value in table["hearing_date"]
                if value.as_py()
            )
            if dates:
                first_dates.append(dates[0])
                latest_dates.append(dates[-1])

    archive_docs, archive_bytes = archive_file_stats()
    return {
        "rulings": rulings,
        "parsed_counties": parsed_counties,
        "source_documents": len(source_hashes) or archive_docs,
        "archive_documents": archive_docs,
        "archive_bytes": archive_bytes,
        "first_hearing_date": min(first_dates) if first_dates else "n/a",
        "latest_hearing_date": max(latest_dates) if latest_dates else "n/a",
    }


def render_live_table(stats: dict[str, int | str]) -> str:
    return f"""\
## LIVE

| Metric | Count |
|---|---:|
| Parsed rulings | {fmt_int(int(stats["rulings"]))} |
| Parsed counties | {fmt_int(int(stats["parsed_counties"]))} |
| Source documents | {fmt_int(int(stats["source_documents"]))} |
| Archived files | {fmt_int(int(stats["archive_documents"]))} |
| Archive size | {fmt_mb(int(stats["archive_bytes"]))} MB |
| Hearing-date coverage | {stats["first_hearing_date"]} to {stats["latest_hearing_date"]} |

Generated by `update-readme.py` from `data/*/rulings.parquet` and `archive/`.
Refresh with `python update-readme.py`.
"""


def with_live_block(content: str, block: str) -> str:
    wrapped = f"{LIVE_START}\n{block.rstrip()}\n{LIVE_END}\n"
    start = content.find(LIVE_START)
    end = content.find(LIVE_END)
    if start != -1 and end != -1 and end > start:
        tail_start = end + len(LIVE_END)
        return content[:start] + wrapped + "\n" + content[tail_start:].lstrip("\n")

    first_break = content.find("\n\n")
    if first_break != -1:
        return content[: first_break + 2] + wrapped + "\n" + content[first_break + 2 :]
    return wrapped + "\n" + content


def main() -> None:
    refresh_site_counties()
    stats = live_stats()
    block = render_live_table(stats)
    LIVE.write_text(block, encoding="utf-8")
    README.write_text(
        with_live_block(README.read_text(encoding="utf-8"), block),
        encoding="utf-8",
    )
    print("Updated README.md and LIVE.md")


if __name__ == "__main__":
    main()
