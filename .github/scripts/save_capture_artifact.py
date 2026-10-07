# visibility: public
"""Preserve added and modified raw captures without copying the full archive."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def save_captures(destination: Path) -> int:
    output = subprocess.run(
        ["git", "ls-files", "--modified", "--others", "--exclude-standard", "-z", "--", "archive/"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    names = sorted(set(p.decode("utf-8") for p in output.split(b"\0") if p))
    paths = []
    for name in names:
        relative = PurePosixPath(name)
        path = ROOT / name
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "archive":
            raise ValueError("Capture path is outside archive")
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()) or not path.is_file():
            raise ValueError(f"Capture is missing or not a regular file: {name}")
        paths.append((name, path))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w") as archive:
        for name, path in paths:
            archive.add(path, arcname=name, recursive=False)
    return len(paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(f"Preserved {save_captures(args.destination)} capture files for artifact upload")
