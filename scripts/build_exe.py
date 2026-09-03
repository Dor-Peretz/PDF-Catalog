from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
LOGO = ROOT / "web" / "logo.png"
ICON = BUILD / "icon.ico"
SPEC = ROOT / "pdf_catalog.spec"


def make_icon() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)
    image = Image.open(LOGO).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    image.save(ICON, format="ICO", sizes=sizes)
    print(f"Wrote {ICON}")


def main() -> None:
    make_icon()
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC),
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)
    exe = ROOT / "dist" / "PDF-Catalog.exe"
    print(f"Built {exe} ({exe.stat().st_size / (1024 * 1024):.1f} MB)")


if __name__ == "__main__":
    main()
