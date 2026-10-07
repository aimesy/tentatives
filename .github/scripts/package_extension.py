# visibility: public
"""Build the same browser packages for releases and public viewer downloads."""

import argparse
import copy
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "extension"


def package_extensions(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    original = json.loads((SOURCE / "manifest.json").read_text())
    files = [path for path in sorted(SOURCE.rglob("*")) if path.is_file()]
    for browser in ("chrome", "firefox"):
        manifest = copy.deepcopy(original)
        if browser == "chrome":
            permissions = manifest.setdefault("permissions", [])
            if "sidePanel" not in permissions:
                permissions.append("sidePanel")
            manifest.pop("sidebar_action", None)
            manifest["side_panel"] = {"default_path": "sidepanel/sidepanel.html"}
            manifest["action"].pop("default_popup", None)
            manifest["background"].pop("scripts", None)
            manifest["description"] = manifest["description"].replace("Sidebar UI", "Side-panel UI")
            manifest["action"]["default_title"] = "Tentatives Capture - open side panel"
        else:
            manifest["background"].pop("service_worker", None)
        destination = output / f"tentatives-extension-{browser}.zip"
        with ZipFile(destination, "w") as archive:
            for path in files:
                name = path.relative_to(SOURCE).as_posix()
                if any(part.startswith(".") for part in Path(name).parts):
                    continue
                info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                content = (json.dumps(manifest, indent=2) + "\n").encode() if name == "manifest.json" else path.read_bytes()
                archive.writestr(info, content)
        print(f"{destination.name}: {destination.stat().st_size} bytes, manifest v{manifest['version']}")
    shutil.copyfile(output / "tentatives-extension-chrome.zip", output / "tentatives-extension.zip")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build")
    package_extensions(parser.parse_args().output)
