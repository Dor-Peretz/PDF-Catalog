from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import db
from app.fs import list_folders
from app.pdf_extract import ocr_status
from app.scanner import (
    cancel_job,
    get_job,
    pause_job,
    reindex_path,
    resume_job,
    start_scan,
)
from app.paths import web_dir
from app.settings import load_settings, save_settings
from app import taxonomy as taxonomy_store

WEB_DIR = web_dir()

app = FastAPI(title="PDF Catalog", docs_url=None, redoc_url=None)
db.init_db().close()


class ScanRequest(BaseModel):
    path: str | None = None
    recursive: bool | None = None
    force: bool = False
    rebuild: bool = False


class CategoryCreate(BaseModel):
    name: str
    keywords: str = ""


class CategoryUpdate(BaseModel):
    name: str | None = None
    keywords: str | None = None


class SubcategoryCreate(BaseModel):
    name: str
    keywords: str = ""


class DocumentClassify(BaseModel):
    category: str
    subcategory: str = ""


class SettingsUpdate(BaseModel):
    folder: str | None = None
    scan_subfolders: bool | None = None
    run_ocr: bool | None = None
    detect_language: bool | None = None
    generate_keywords: bool | None = None
    ocr_hebrew: bool | None = None
    ocr_english: bool | None = None


def _open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _public_document(item: dict) -> dict:
    item["dates"] = json.loads(item.get("dates_json") or "[]")
    item.pop("dates_json", None)
    folder = str(Path(item["path"]).parent) if item.get("path") else ""
    item["folder"] = folder
    return item


@app.post("/api/quit")
def quit_app() -> dict:
    def stop() -> None:
        time.sleep(0.25)
        os._exit(0)

    threading.Thread(target=stop, daemon=True).start()
    return {"ok": True}


@app.get("/api/status")
def status() -> dict:
    conn = db.get_connection()
    try:
        settings = load_settings()
        return {
            "documents": db.document_count(conn),
            "database_size": db.database_size(),
            "ocr": ocr_status(),
            "folder": settings.get("folder") or "",
            "settings": settings,
        }
    finally:
        conn.close()


@app.get("/api/settings")
def get_settings() -> dict:
    return load_settings()


@app.put("/api/settings")
def update_settings(body: SettingsUpdate) -> dict:
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    return save_settings(payload)


@app.get("/api/fs")
def filesystem(path: str = "") -> dict:
    return list_folders(path)


@app.post("/api/pick-folder")
def pick_folder() -> dict:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = 'Choose a PDF folder'; "
        "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    path = (result.stdout or "").strip()
    if not path:
        return {"path": None, "cancelled": True}
    save_settings({"folder": path})
    return {"path": path, "cancelled": False}


@app.post("/api/scan")
def scan_folder(body: ScanRequest) -> dict:
    try:
        return start_scan(
            body.path,
            recursive=body.recursive,
            force=body.force,
            rebuild=body.rebuild,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/jobs/{job_id}/pause")
def job_pause(job_id: str) -> dict:
    try:
        return pause_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None


@app.post("/api/jobs/{job_id}/resume")
def job_resume(job_id: str) -> dict:
    try:
        return resume_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict:
    try:
        return cancel_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found") from None


@app.get("/api/search")
def search(
    q: str = "",
    category: str = "",
    categories: str = "",
    subcategories: str = "",
    language: str = "",
    ocr: str = "",
    folder: str = "",
    sort: str = "relevance",
    limit: int = 100,
) -> dict:
    selected = [part for part in categories.split(",") if part]
    sub_pairs: list[tuple[str, str]] = []
    for part in subcategories.split(",") if subcategories else []:
        if ">>" in part:
            parent, child = part.split(">>", 1)
            if parent and child:
                sub_pairs.append((parent, child))
    ocr_states = [part for part in ocr.split(",") if part]
    conn = db.get_connection()
    try:
        results, matches = db.search_documents(
            conn,
            query=q,
            category=category or None,
            categories=selected,
            subcategories=sub_pairs,
            language=language or None,
            ocr_states=ocr_states,
            folder=folder or None,
            sort=sort,
            limit=min(max(limit, 1), 500),
        )
        for item in results:
            item.pop("full_text", None)
            _public_document(item)
        return {
            "results": results,
            "matches": matches,
            "total": db.document_count(conn),
        }
    finally:
        conn.close()


@app.get("/api/documents/{document_id}")
def document_detail(document_id: int) -> dict:
    conn = db.get_connection()
    try:
        item = db.get_document(conn, document_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return _public_document(item)
    finally:
        conn.close()


@app.post("/api/documents/{document_id}/open")
def open_document(document_id: int) -> dict:
    conn = db.get_connection()
    try:
        item = db.get_document(conn, document_id)
    finally:
        conn.close()
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = item["path"]
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="File is no longer on disk")
    try:
        _open_path(path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": path}


@app.post("/api/documents/{document_id}/open-folder")
def open_document_folder(document_id: int) -> dict:
    conn = db.get_connection()
    try:
        item = db.get_document(conn, document_id)
    finally:
        conn.close()
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found")
    folder = str(Path(item["path"]).parent)
    if not Path(folder).exists():
        raise HTTPException(status_code=404, detail="Folder is no longer on disk")
    try:
        _open_path(folder)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "path": folder}


@app.post("/api/documents/{document_id}/reindex")
def reindex_document(document_id: int) -> dict:
    conn = db.get_connection()
    try:
        item = db.get_document(conn, document_id)
    finally:
        conn.close()
    if item is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(item["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File is no longer on disk")
    try:
        return reindex_path(path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.patch("/api/documents/{document_id}")
def classify_document(document_id: int, body: DocumentClassify) -> dict:
    conn = db.get_connection()
    try:
        item = db.update_document_classification(
            conn, document_id, body.category.strip(), body.subcategory.strip()
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return _public_document(item)
    finally:
        conn.close()


@app.get("/api/taxonomy")
def get_taxonomy() -> dict:
    return {"categories": taxonomy_store.load_taxonomy()}


@app.post("/api/taxonomy/categories")
def create_category(body: CategoryCreate) -> dict:
    try:
        return taxonomy_store.add_category(body.name, body.keywords)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/taxonomy/categories/{category_id}")
def edit_category(category_id: str, body: CategoryUpdate) -> dict:
    existing = taxonomy_store.get_category(category_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Category not found")
    old_name = existing["name"]
    try:
        updated = taxonomy_store.update_category(
            category_id,
            **{key: value for key, value in body.model_dump().items() if value is not None},
        )
    except (KeyError, ValueError) as exc:
        status = 404 if isinstance(exc, KeyError) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    if updated["name"] != old_name:
        conn = db.get_connection()
        try:
            db.rename_classification(conn, old_category=old_name, new_category=updated["name"])
        finally:
            conn.close()
    return updated


@app.delete("/api/taxonomy/categories/{category_id}")
def remove_category(category_id: str) -> dict:
    try:
        removed = taxonomy_store.delete_category(category_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Category not found") from None
    conn = db.get_connection()
    try:
        db.clear_category_documents(conn, removed["name"])
    finally:
        conn.close()
    return {"ok": True, "removed": removed}


@app.post("/api/taxonomy/categories/{category_id}/subcategories")
def create_subcategory(category_id: str, body: SubcategoryCreate) -> dict:
    try:
        return taxonomy_store.add_subcategory(category_id, body.name, body.keywords)
    except KeyError:
        raise HTTPException(status_code=404, detail="Category not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/taxonomy/categories/{category_id}/subcategories/{subcategory_id}")
def remove_subcategory(category_id: str, subcategory_id: str) -> dict:
    parent = taxonomy_store.get_category(category_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        removed = taxonomy_store.delete_subcategory(category_id, subcategory_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Not found") from None
    conn = db.get_connection()
    try:
        db.clear_subcategory_documents(conn, parent["name"], removed["name"])
    finally:
        conn.close()
    return {"ok": True, "removed": removed}


@app.get("/api/categories")
def categories() -> dict:
    conn = db.get_connection()
    try:
        return {"categories": db.category_counts(conn)}
    finally:
        conn.close()


@app.get("/api/filters")
def filters() -> dict:
    conn = db.get_connection()
    try:
        return {
            "taxonomy": taxonomy_store.load_taxonomy(),
            "categories": db.category_counts(conn),
            "languages": db.language_counts(conn),
            "ocr": db.ocr_counts(conn),
            "total": db.document_count(conn),
        }
    finally:
        conn.close()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
