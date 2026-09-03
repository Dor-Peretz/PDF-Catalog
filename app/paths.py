from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PDF-Catalog"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    if is_frozen():
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
    else:
        base = Path(__file__).resolve().parent.parent / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def web_dir() -> Path:
    return resource_root() / "web"


def stopwords_path() -> Path:
    return resource_root() / "data" / "hebrew_stopwords.txt"


def tessdata_dir() -> Path:
    return resource_root() / "data" / "tessdata"


def bundled_tesseract() -> Path | None:
    candidate = resource_root() / "tesseract" / "tesseract.exe"
    return candidate if candidate.exists() else None
