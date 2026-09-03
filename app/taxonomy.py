from __future__ import annotations

import json
import uuid
from typing import Any

from app.paths import user_data_dir

TAXONOMY_PATH = user_data_dir() / "categories.json"

DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {
        "name": "חשבונית",
        "keywords": "חשבונית, חשבוניות, invoice, invoices, מע״מ, מעמ, vat",
        "builtin": True,
        "subcategories": [],
    },
    {
        "name": "קבלה",
        "keywords": "קבלה, קבלות, receipt, receipts",
        "builtin": True,
        "subcategories": [],
    },
    {
        "name": "חוזה",
        "keywords": "חוזה, חוזים, הסכם, הסכמים, contract, agreement",
        "builtin": True,
        "subcategories": [],
    },
    {
        "name": "תעודה",
        "keywords": "תעודה, תעודת, תעודות, certificate, diploma",
        "builtin": True,
        "subcategories": [],
    },
    {
        "name": "מכתב",
        "keywords": "מכתב, מכתבים, letter, correspondence",
        "builtin": True,
        "subcategories": [],
    },
    {
        "name": "דוח",
        "keywords": "דוח, דוחות, report, reports",
        "builtin": True,
        "subcategories": [],
    },
    {
        "name": "אחר",
        "keywords": "",
        "builtin": True,
        "subcategories": [],
    },
]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _normalize_category(raw: dict[str, Any]) -> dict[str, Any]:
    subs = []
    for sub in raw.get("subcategories") or []:
        if isinstance(sub, str):
            sub = {"name": sub}
        name = str(sub.get("name") or "").strip()
        if not name:
            continue
        subs.append(
            {
                "id": str(sub.get("id") or _new_id("s")),
                "name": name,
                "keywords": str(sub.get("keywords") or "").strip(),
            }
        )
    return {
        "id": str(raw.get("id") or _new_id("c")),
        "name": str(raw.get("name") or "").strip(),
        "keywords": str(raw.get("keywords") or "").strip(),
        "builtin": bool(raw.get("builtin", False)),
        "subcategories": subs,
    }


def _defaults() -> list[dict[str, Any]]:
    return [_normalize_category(item) for item in DEFAULT_CATEGORIES]


def load_taxonomy() -> list[dict[str, Any]]:
    if not TAXONOMY_PATH.exists():
        data = _defaults()
        save_taxonomy(data)
        return data
    try:
        payload = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _defaults()
    items = payload.get("categories", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return _defaults()
    normalized = [_normalize_category(item) for item in items if str(item.get("name") or "").strip()]
    return normalized or _defaults()


def save_taxonomy(categories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [_normalize_category(item) for item in categories if str(item.get("name") or "").strip()]
    TAXONOMY_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAXONOMY_PATH.write_text(
        json.dumps({"categories": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def get_category(category_id: str) -> dict[str, Any] | None:
    for item in load_taxonomy():
        if item["id"] == category_id:
            return item
    return None


def add_category(name: str, keywords: str = "") -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Category name is required")
    categories = load_taxonomy()
    if any(item["name"].casefold() == name.casefold() for item in categories):
        raise ValueError("A category with this name already exists")
    item = _normalize_category({"name": name, "keywords": keywords, "builtin": False, "subcategories": []})
    categories.append(item)
    save_taxonomy(categories)
    return item


def update_category(category_id: str, **fields: Any) -> dict[str, Any]:
    categories = load_taxonomy()
    found = None
    for item in categories:
        if item["id"] == category_id:
            found = item
            break
    if found is None:
        raise KeyError(category_id)
    if "name" in fields:
        name = str(fields["name"] or "").strip()
        if not name:
            raise ValueError("Category name is required")
        if any(item["id"] != category_id and item["name"].casefold() == name.casefold() for item in categories):
            raise ValueError("A category with this name already exists")
        found["name"] = name
    if "keywords" in fields:
        found["keywords"] = str(fields["keywords"] or "").strip()
    save_taxonomy(categories)
    return found


def delete_category(category_id: str) -> dict[str, Any]:
    categories = load_taxonomy()
    found = next((item for item in categories if item["id"] == category_id), None)
    if found is None:
        raise KeyError(category_id)
    remaining = [item for item in categories if item["id"] != category_id]
    save_taxonomy(remaining)
    return found


def add_subcategory(category_id: str, name: str, keywords: str = "") -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Subcategory name is required")
    categories = load_taxonomy()
    parent = next((item for item in categories if item["id"] == category_id), None)
    if parent is None:
        raise KeyError(category_id)
    if any(sub["name"].casefold() == name.casefold() for sub in parent["subcategories"]):
        raise ValueError("A subcategory with this name already exists")
    sub = {"id": _new_id("s"), "name": name, "keywords": keywords.strip()}
    parent["subcategories"].append(sub)
    save_taxonomy(categories)
    return sub


def delete_subcategory(category_id: str, subcategory_id: str) -> dict[str, Any]:
    categories = load_taxonomy()
    parent = next((item for item in categories if item["id"] == category_id), None)
    if parent is None:
        raise KeyError(category_id)
    found = next((sub for sub in parent["subcategories"] if sub["id"] == subcategory_id), None)
    if found is None:
        raise KeyError(subcategory_id)
    parent["subcategories"] = [sub for sub in parent["subcategories"] if sub["id"] != subcategory_id]
    save_taxonomy(categories)
    return found
