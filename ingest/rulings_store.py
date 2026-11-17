"""A county's rulings, stored as one Parquet file or several.

GitHub refuses any file over 100 MiB, and Los Angeles's rulings.parquet passed
that on 2026-11-11, so every later harvest failed to push its parsed data. A
county whose table would exceed MAX_SHARD_BYTES is written as rulings.parquet
plus rulings-002.parquet, rulings-003.parquet, ... (contiguous row ranges, in
order). Smaller counties keep exactly one rulings.parquet, as before.

Read a county with `read_county_table`, never `pq.read_table` on
rulings.parquet alone, or the later shards' rows are missed.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

PRIMARY = "rulings.parquet"
SHARD = re.compile(r"^rulings-(\d{3})\.parquet$")
# GitHub's hard limit is 100 MiB; leave room for the next day's rows.
MAX_SHARD_BYTES = 90 * 1024 * 1024
WRITE_OPTIONS = {"compression": "zstd", "compression_level": 9}


def shard_name(index: int) -> str:
    return PRIMARY if index == 1 else f"rulings-{index:03d}.parquet"


def county_parquet_paths(county_dir: Path) -> list[Path]:
    """rulings.parquet first, then its shards in order; [] if the county has none."""
    primary = county_dir / PRIMARY
    if not primary.exists():
        return []
    shards = sorted(
        (int(m.group(1)), p)
        for p in county_dir.iterdir()
        if (m := SHARD.match(p.name)) and int(m.group(1)) >= 2
    )
    return [primary, *(p for _, p in shards)]


def has_rulings(county_dir: Path) -> bool:
    return (county_dir / PRIMARY).exists()


def read_county_table(county_dir: Path, columns: list[str] | None = None) -> pa.Table:
    paths = county_parquet_paths(county_dir)
    if not paths:
        raise FileNotFoundError(county_dir / PRIMARY)
    tables = [pq.read_table(p, columns=columns) for p in paths]
    if len(tables) == 1:
        return tables[0]
    return pa.concat_tables(tables, promote_options="default")


def county_num_rows(county_dir: Path) -> int:
    return sum(int(pq.read_metadata(p).num_rows or 0) for p in county_parquet_paths(county_dir))


def county_schema(county_dir: Path) -> pa.Schema:
    return pq.read_schema(county_parquet_paths(county_dir)[0])


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def county_digest(county_dir: Path) -> str:
    """The primary file's sha256 when there is one file (unchanged from before);
    otherwise the sha256 of every shard's name and sha256."""
    paths = county_parquet_paths(county_dir)
    if not paths:
        raise FileNotFoundError(county_dir / PRIMARY)
    if len(paths) == 1:
        return _file_sha256(paths[0])
    joined = "".join(f"{p.name} {_file_sha256(p)}\n" for p in paths)
    return hashlib.sha256(joined.encode()).hexdigest()


def _write_tmp(table: pa.Table, county_dir: Path, name: str) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix=f".{name}.", suffix=".tmp", dir=county_dir, delete=False)
    tmp = Path(handle.name)
    handle.close()
    pq.write_table(table, tmp, **WRITE_OPTIONS)
    return tmp


def write_county_table(table: pa.Table, county_dir: Path, *, max_bytes: int = MAX_SHARD_BYTES) -> list[Path]:
    """Write `table` as the county's rulings, split so no file exceeds max_bytes.

    Shards beyond the new count are removed. Returns the paths written.
    """
    county_dir.mkdir(parents=True, exist_ok=True)
    tmps: list[Path] = []
    try:
        tmps = [_write_tmp(table, county_dir, PRIMARY)]
        size = tmps[0].stat().st_size
        parts = 1
        while size > max_bytes:
            if parts >= max(table.num_rows, 1):
                raise ValueError(f"cannot split {county_dir.name} rulings under {max_bytes} bytes")
            for tmp in tmps:
                tmp.unlink(missing_ok=True)
            # Aim for 80% of the limit so a skewed slice still fits.
            parts = max(parts + 1, math.ceil(size / (max_bytes * 0.8)))
            step = math.ceil(table.num_rows / parts)
            tmps = [
                _write_tmp(table.slice(i * step, step), county_dir, shard_name(i + 1))
                for i in range(parts)
                if i * step < table.num_rows
            ]
            parts = len(tmps)
            size = max(t.stat().st_size for t in tmps)
        finals = [county_dir / shard_name(i + 1) for i in range(len(tmps))]
        # Shards first, the primary last, then drop shards the table no longer needs.
        for tmp, final in reversed(list(zip(tmps, finals))):
            os.replace(tmp, final)
        tmps = []
        for stale in county_parquet_paths(county_dir)[len(finals):]:
            stale.unlink()
        return finals
    finally:
        for tmp in tmps:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
