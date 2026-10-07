# visibility: public
"""List only archived regression sources named by the county tests.

The archive holds many gigabytes of captures in aimesy/tentatives-data. Reading
its Git tree does not download those blobs; sparse checkout then fetches only
sources used by tests. Pass the data checkout's path; it defaults to this
checkout, for a tree with the code copied into the data.
"""

from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
DATA = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
hashes = {
    sha
    for path in (ROOT / "counties").rglob("test*.py")
    for sha in re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", path.read_text())
}
tree = subprocess.run(
    ["git", "ls-tree", "-r", "--name-only", "HEAD", "--", "archive"],
    cwd=DATA,
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()
for path in sorted(tree):
    if PurePosixPath(path).stem in hashes or path == "archive/el-dorado/captures.ndjson":
        print(f"/{path}")
