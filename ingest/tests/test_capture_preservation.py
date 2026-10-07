# visibility: public
"""Prove concurrent publication keeps real archived capture fields and bytes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ".github" / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resolver = load_script("resolve_capture_rebase")
salvage = load_script("save_capture_artifact")


class CapturePreservationTests(unittest.TestCase):
    def test_recheck_preserves_every_field_in_real_archived_manifest(self):
        source = (ROOT / "archive/el-dorado/captures.ndjson").read_bytes()
        existing = [json.loads(line) for line in source.splitlines() if line.strip()]
        self.assertTrue(existing)
        changed = dict(existing[-1])
        changed["source_sha256"] = "f" * 64
        changed["new_source_notice"] = {"text": "Court notice", "values": [None, False, 0, ""]}
        upstream = source + json.dumps(changed).encode() + b"\n"
        local = source + json.dumps(changed, sort_keys=True).encode() + b"\n"
        result = [json.loads(line) for line in resolver.merge_manifests(source, upstream, local).splitlines()]
        self.assertEqual(result[:len(existing)], existing)
        self.assertEqual(result[len(existing):], [changed])

    def test_existing_duplicate_provenance_is_preserved(self):
        row = b'{"source_sha256":"abc","source_url":"https://court.test/source.pdf","notice":{"full":"text"}}\n'
        self.assertEqual(resolver.merge_manifests(row * 2, row * 2, row), row * 2)

    def test_invalid_manifest_is_rejected(self):
        with self.assertRaises(ValueError):
            resolver.merge_manifests(b'{"source_url":"https://court.test/"}\n')

    def test_artifact_preserves_added_bytes_and_complete_modified_manifest(self):
        source = (ROOT / "archive/el-dorado/captures.ndjson").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "archive/el-dorado/captures.ndjson"
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(source)
            pdf = root / "archive/el-dorado/ff/new.pdf"
            pdf.parent.mkdir()
            pdf.write_bytes(b"%PDF-1.7\ncomplete captured bytes\n")
            status = subprocess.CompletedProcess([], 0, b"archive/el-dorado/captures.ndjson\0archive/el-dorado/ff/new.pdf\0")
            target = root / "saved.tar"
            with patch.object(salvage, "ROOT", root), patch.object(salvage.subprocess, "run", return_value=status):
                self.assertEqual(salvage.save_captures(target), 2)
            with tarfile.open(target) as archive:
                self.assertEqual(archive.extractfile("archive/el-dorado/captures.ndjson").read(), source)
                self.assertEqual(archive.extractfile("archive/el-dorado/ff/new.pdf").read(), pdf.read_bytes())


if __name__ == "__main__":
    unittest.main()
