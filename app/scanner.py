from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import db
from app.keywords import analyze_text
from app.pdf_extract import extract_pdf, ocr_status
from app.settings import load_settings, ocr_lang, save_settings

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
_scan_lock = threading.Lock()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def walk_pdfs(root: Path, recursive: bool = True) -> list[Path]:
    iterator = root.rglob("*.pdf") if recursive else root.glob("*.pdf")
    return sorted(path for path in iterator if path.is_file())


def get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _update_job(job_id: str, **changes: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(changes)


def _append_error(job_id: str, path: str, message: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        errors = list(job.get("errors") or [])
        errors.append({"path": path, "error": message})
        job["errors"] = errors[-50:]


def _job_flag(job_id: str, name: str) -> bool:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return bool(job and job.get(name))


def _wait_if_paused(job_id: str) -> None:
    while _job_flag(job_id, "paused") and not _job_flag(job_id, "cancelled"):
        _update_job(job_id, status="paused", stage="Paused")
        time.sleep(0.25)


def start_scan(
    folder: str | None = None,
    *,
    recursive: bool | None = None,
    force: bool = False,
    rebuild: bool = False,
) -> dict[str, Any]:
    settings = load_settings()
    folder_path = folder or settings.get("folder") or ""
    root = Path(folder_path).expanduser()
    if not folder_path or not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder_path or '(none)'}")

    resolved = str(root.resolve())
    save_settings({"folder": resolved})
    if recursive is None:
        recursive = bool(settings.get("scan_subfolders", True))

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "status": "queued",
        "path": resolved,
        "total": 0,
        "done": 0,
        "skipped": 0,
        "indexed": 0,
        "current_file": None,
        "stage": "Listing PDFs",
        "errors": [],
        "paused": False,
        "cancelled": False,
        "ocr": ocr_status(),
    }
    with _jobs_lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_scan,
        args=(job_id, root, recursive, force, rebuild),
        daemon=True,
    )
    thread.start()
    return dict(job)


def cancel_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    _update_job(job_id, cancelled=True, paused=False, status="cancelling", stage="Cancelling")
    return get_job(job_id) or job


def pause_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.get("status") not in {"running", "queued", "paused"}:
        return job
    _update_job(job_id, paused=True, status="paused", stage="Paused")
    return get_job(job_id) or job


def resume_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    _update_job(job_id, paused=False, status="running")
    return get_job(job_id) or job


def _keyword_stats(conn) -> tuple[dict[str, int], int]:
    rows = conn.execute("SELECT keyword FROM keywords").fetchall()
    freq: dict[str, int] = {}
    for row in rows:
        freq[row[0]] = freq.get(row[0], 0) + 1
    return freq, db.document_count(conn)


def index_file(
    conn,
    path: Path,
    doc_frequencies: dict[str, int],
    corpus_size: int,
    *,
    force: bool = False,
    job_id: str | None = None,
) -> str:
    settings = load_settings()
    resolved = str(path.resolve())
    digest = sha256_file(path)
    stat = path.stat()
    existing = db.find_by_path(conn, resolved)
    if existing and existing["sha256"] == digest and not force:
        return "skipped"

    def on_stage(name: str) -> None:
        if job_id:
            _update_job(job_id, stage=name, current_file=path.name)

    extracted = extract_pdf(
        path,
        run_ocr=bool(settings.get("run_ocr", True)),
        ocr_lang=ocr_lang(settings),
        on_stage=on_stage,
    )
    if settings.get("detect_language", True) or settings.get("generate_keywords", True):
        if job_id:
            _update_job(job_id, stage="Detecting language")
        analysis = analyze_text(extracted["text"], doc_frequencies, corpus_size)
        if not settings.get("generate_keywords", True):
            analysis["keywords"] = []
        if not settings.get("detect_language", True):
            analysis["language"] = "unknown"
    else:
        analysis = {
            "keywords": [],
            "category": "אחר",
            "dates": [],
            "language": "unknown",
        }
    if job_id:
        _update_job(job_id, stage="Saving index")
    db.upsert_document(
        conn,
        path=resolved,
        filename=path.name,
        sha256=digest,
        size=stat.st_size,
        mtime=stat.st_mtime,
        page_count=extracted["page_count"],
        is_scanned=bool(extracted["is_scanned"]),
        language=analysis["language"],
        category=analysis["category"],
        dates_json=json.dumps(analysis["dates"], ensure_ascii=False),
        full_text=extracted["text"],
        keywords=analysis["keywords"],
        error=extracted["error"],
        indexed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    for word, _score in analysis["keywords"]:
        doc_frequencies[word] = doc_frequencies.get(word, 0) + 1
    return "indexed"


def reindex_path(path: Path) -> dict[str, Any]:
    conn = db.init_db()
    try:
        frequencies, corpus_size = _keyword_stats(conn)
        result = index_file(conn, path, frequencies, corpus_size, force=True)
        row = db.find_by_path(conn, str(path.resolve()))
        return {"result": result, "document": dict(row) if row else None}
    finally:
        conn.close()


def _run_scan(job_id: str, root: Path, recursive: bool, force: bool, rebuild: bool) -> None:
    _update_job(job_id, status="running", stage="Listing PDFs")
    with _scan_lock:
        try:
            pdfs = walk_pdfs(root, recursive=recursive)
            _update_job(job_id, total=len(pdfs))
            conn = db.init_db()
            try:
                if rebuild:
                    _update_job(job_id, stage="Clearing index")
                    db.clear_index(conn)
                frequencies, corpus_size = _keyword_stats(conn)
                for index, pdf in enumerate(pdfs, start=1):
                    if _job_flag(job_id, "cancelled"):
                        _update_job(job_id, status="cancelled", stage="Cancelled", current_file=None)
                        return
                    _wait_if_paused(job_id)
                    if _job_flag(job_id, "cancelled"):
                        _update_job(job_id, status="cancelled", stage="Cancelled", current_file=None)
                        return
                    _update_job(
                        job_id,
                        status="running",
                        current_file=pdf.name,
                        stage="Reading PDF",
                        done=index - 1,
                    )
                    try:
                        result = index_file(
                            conn,
                            pdf,
                            frequencies,
                            corpus_size + index - 1,
                            force=force or rebuild,
                            job_id=job_id,
                        )
                        if result == "skipped":
                            with _jobs_lock:
                                _jobs[job_id]["skipped"] += 1
                        else:
                            with _jobs_lock:
                                _jobs[job_id]["indexed"] += 1
                    except Exception as exc:
                        _append_error(job_id, str(pdf), str(exc))
                    _update_job(job_id, done=index)
            finally:
                conn.close()
            if _job_flag(job_id, "cancelled"):
                _update_job(job_id, status="cancelled", stage="Cancelled", current_file=None)
                return
            _update_job(job_id, status="done", stage="Done", current_file=None)
        except Exception as exc:
            _update_job(job_id, status="error", stage="Error", current_file=None)
            _append_error(job_id, str(root), str(exc))
