from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.paths import user_data_dir

SETTINGS_PATH = user_data_dir() / "settings.json"

DEFAULTS: dict[str, Any] = {
    "folder": "",
    "scan_subfolders": True,
    "run_ocr": True,
    "detect_language": True,
    "generate_keywords": True,
    "ocr_hebrew": True,
    "ocr_english": True,
}


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({key: data[key] for key in DEFAULTS if key in data})
    return merged


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    for key, value in updates.items():
        if key in DEFAULTS:
            current[key] = value
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


def ocr_lang(settings: dict[str, Any] | None = None) -> str:
    settings = settings or load_settings()
    parts: list[str] = []
    if settings.get("ocr_hebrew", True):
        parts.append("heb")
    if settings.get("ocr_english", True):
        parts.append("eng")
    return "+".join(parts) or "heb+eng"
