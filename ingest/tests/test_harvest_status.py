"""The courtproj harvest's recheck rules (ops/harvest_status.py) and the
backfill options it depends on."""

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

from ingest import backfill

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("harvest_status", ROOT / "ops" / "harvest_status.py")
harvest_status = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harvest_status)
reason = harvest_status.recheck_reason

TODAY = "2026-10-07"


def test_gone_files_are_not_rechecked():
    result = {"refs": 320, "failures": ["ERROR fetch https://x/a.pdf wayback=-: 404 Client Error: Not Found for url: https://x/a.pdf"]}
    assert reason(result, {}, TODAY) is None


def test_refused_fetch_is_rechecked():
    result = {"refs": 7, "failures": ["ERROR fetch https://x/b.pdf wayback=-: 403 Client Error: Forbidden for url: https://x/b.pdf"]}
    assert reason(result, {}, TODAY).startswith("fetch:")


def test_timeout_without_status_is_rechecked():
    result = {"refs": 3, "failures": ["ERROR fetch https://x/c.pdf wayback=-: Read timed out. (read timeout=60)"]}
    assert reason(result, {}, TODAY).startswith("fetch:")


def test_discovery_failure_is_rechecked():
    result = {"refs": 0, "failures": ["ERROR live discovery for marin: 503 Server Error"]}
    assert reason(result, {}, TODAY).startswith("discovery:")


def test_warnings_alone_do_not_recheck():
    result = {"refs": 17, "failures": ["WARN discover landing https://x failed; trying reader fallback: 403 Client Error"]}
    assert reason(result, {}, TODAY) is None


def test_empty_county_rechecked_only_when_recently_productive():
    empty = {"refs": 0, "pages": 0, "failures": []}
    assert reason(empty, {"last_productive": "2026-10-01"}, TODAY).startswith("captured nothing")
    assert reason(empty, {"last_productive": "2026-09-01"}, TODAY) is None
    assert reason(empty, {}, TODAY) is None


def test_skipped_and_raised_counties():
    assert reason({"skipped": "historical only"}, {"last_productive": TODAY}, TODAY) is None
    assert reason({"exception": "ValueError: bad page"}, {}, TODAY).startswith("error:")


def run_status(*argv):
    import subprocess, sys
    return subprocess.run([sys.executable, str(ROOT / "ops" / "harvest_status.py"), *argv], capture_output=True, text=True, check=True).stdout.strip()


def test_capture_records_counties_and_prints_rechecks(tmp_path):
    status = tmp_path / "status" / "harvest.json"
    status.parent.mkdir()
    status.write_text(json.dumps({"counties": {"sonoma": {"last_productive": "2026-10-05"}}, "fallback": {"date": "2026-10-06"}}))
    run_status("start", str(status), "--date", TODAY, "--code", "abc")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({
        "yolo": {"discovered": 320, "refs": 320, "pages": 0, "failures": ["ERROR fetch u wayback=-: 404 Client Error: Not Found for url: u"]},
        "marin": {"discovered": 11, "refs": 7, "pages": 0, "failures": ["ERROR fetch u wayback=-: 403 Client Error: Forbidden for url: u"]},
        "sonoma": {"discovered": 0, "refs": 0, "pages": 0, "failures": []},
        "amador": {"skipped": "historical only"},
    }))
    assert run_status("capture", str(status), "--summary", str(summary), "--exit", "0") == "marin,sonoma"
    data = json.loads(status.read_text())
    assert data["capture"] == "ok" and data["stage"] == "captured"
    assert data["counties"]["yolo"]["last_productive"] == TODAY
    assert data["counties"]["sonoma"]["last_productive"] == "2026-10-05"
    assert data["fallback"] == {"date": "2026-10-06"}
    run_status("parse", str(status), "--result", "ok")
    assert json.loads(status.read_text())["stage"] == "done"


def test_capture_with_nothing_captured_fails(tmp_path):
    status = tmp_path / "harvest.json"
    run_status("start", str(status), "--date", TODAY, "--code", "abc")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"yolo": {"refs": 0, "pages": 0, "failures": []}}))
    assert run_status("capture", str(status), "--summary", str(summary), "--exit", "0") == "all"
    assert json.loads(status.read_text())["capture"] == "failed"


def test_county_list_option():
    some = sorted(backfill.COUNTY_MODULES)[:2]
    assert backfill._county_list("all") == "all"
    assert backfill._county_list(f" {some[1]},{some[0]},{some[1]} ") == f"{some[1]},{some[0]}"
    with pytest.raises(argparse.ArgumentTypeError):
        backfill._county_list("atlantis")
