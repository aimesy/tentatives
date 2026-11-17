import hashlib
import os

import pyarrow as pa
import pyarrow.parquet as pq

from ingest import rulings_store as store


def table(n: int) -> pa.Table:
    return pa.table({
        "ruling_id": [f"{i:032x}" for i in range(n)],
        "body_text": [os.urandom(2000).hex() for _ in range(n)],
    })


def test_small_county_stays_one_file(tmp_path):
    written = store.write_county_table(table(5), tmp_path)
    assert [p.name for p in written] == ["rulings.parquet"]
    assert [p.name for p in store.county_parquet_paths(tmp_path)] == ["rulings.parquet"]
    # One file: the digest is the file's own sha256, as before sharding.
    assert store.county_digest(tmp_path) == hashlib.sha256((tmp_path / "rulings.parquet").read_bytes()).hexdigest()


def test_large_county_splits_and_reads_back_in_order(tmp_path):
    source = table(200)
    written = store.write_county_table(source, tmp_path, max_bytes=150_000)
    assert len(written) > 1
    assert written[0].name == "rulings.parquet"
    assert all(p.stat().st_size <= 150_000 for p in written)
    assert store.read_county_table(tmp_path).equals(source)
    assert store.county_num_rows(tmp_path) == 200
    assert store.read_county_table(tmp_path, columns=["ruling_id"]).column(0).to_pylist() == source["ruling_id"].to_pylist()
    assert not list(tmp_path.glob(".*.tmp"))


def test_shrinking_removes_stale_shards(tmp_path):
    store.write_county_table(table(200), tmp_path, max_bytes=150_000)
    assert len(store.county_parquet_paths(tmp_path)) > 1
    small = table(3)
    store.write_county_table(small, tmp_path, max_bytes=150_000)
    assert [p.name for p in tmp_path.glob("*.parquet")] == ["rulings.parquet"]
    assert store.read_county_table(tmp_path).equals(small)


def test_digest_changes_with_any_shard(tmp_path):
    store.write_county_table(table(200), tmp_path, max_bytes=150_000)
    before = store.county_digest(tmp_path)
    last = store.county_parquet_paths(tmp_path)[-1]
    rows = pq.read_table(last)
    pq.write_table(rows.slice(0, rows.num_rows - 1), last)
    assert store.county_digest(tmp_path) != before


def test_orchestrate_appends_across_shards(tmp_path, monkeypatch):
    from ingest import orchestrate

    store.write_county_table(table(200), tmp_path, max_bytes=150_000)
    ids = orchestrate.existing_ruling_ids(tmp_path / "rulings.parquet")
    assert len(ids) == 200
