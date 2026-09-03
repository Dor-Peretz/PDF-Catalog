from __future__ import annotations

import string
from pathlib import Path

from fastapi import HTTPException


def list_drives() -> list[dict[str, str]]:
    drives: list[dict[str, str]] = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:/")
        if root.exists():
            drives.append({"name": f"{letter}:", "path": f"{letter}:\\"})
    return drives


def _is_drive_root(path: Path) -> bool:
    text = str(path)
    return path.parent == path or (len(text) <= 3 and text.endswith(("\\", "/", ":")))


def list_folders(path: str) -> dict:
    if not (path or "").strip():
        return {"path": "", "parent": None, "entries": list_drives()}

    target = Path(path.strip())
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc

    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Folder not found")

    parent = "" if _is_drive_root(resolved) else str(resolved.parent)
    entries: list[dict[str, str]] = []
    try:
        children = list(resolved.iterdir())
    except OSError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    for child in sorted(children, key=lambda item: item.name.lower()):
        try:
            if child.is_dir():
                entries.append({"name": child.name, "path": str(child)})
        except OSError:
            continue

    return {"path": str(resolved), "parent": parent, "entries": entries}
