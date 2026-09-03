from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.paths import user_data_dir

DATA_DIR = user_data_dir()
DB_PATH = DATA_DIR / "catalog.db"

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER,
    mtime REAL,
    page_count INTEGER,
    is_scanned INTEGER DEFAULT 0,
    language TEXT,
    category TEXT,
    subcategory TEXT,
    dates_json TEXT,
    full_text TEXT,
    error TEXT,
    indexed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);

CREATE TABLE IF NOT EXISTS keywords (
    document_id INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    score REAL NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_keywords_document ON keywords(document_id);
CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON keywords(keyword);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    filename,
    full_text,
    keywords,
    category,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    own = conn is None
    if conn is None:
        conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    conn.commit()
    if own:
        return conn
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "subcategory" not in columns:
        conn.execute("ALTER TABLE documents ADD COLUMN subcategory TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_subcategory ON documents(subcategory)")


def find_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE path = ?", (path,)).fetchone()


def find_by_hash(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE sha256 = ? ORDER BY indexed_at DESC LIMIT 1",
        (sha256,),
    ).fetchone()


def delete_document(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (document_id,))
    conn.execute("DELETE FROM keywords WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))


def upsert_document(
    conn: sqlite3.Connection,
    *,
    path: str,
    filename: str,
    sha256: str,
    size: int,
    mtime: float,
    page_count: int | None,
    is_scanned: bool,
    language: str,
    category: str,
    subcategory: str = "",
    dates_json: str,
    full_text: str,
    keywords: list[tuple[str, float]],
    error: str | None,
    indexed_at: str,
) -> int:
    existing = find_by_path(conn, path)
    if existing:
        delete_document(conn, int(existing["id"]))

    cur = conn.execute(
        """
        INSERT INTO documents (
            path, filename, sha256, size, mtime, page_count, is_scanned,
            language, category, subcategory, dates_json, full_text, error, indexed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            path,
            filename,
            sha256,
            size,
            mtime,
            page_count,
            1 if is_scanned else 0,
            language,
            category,
            subcategory or "",
            dates_json,
            full_text,
            error,
            indexed_at,
        ),
    )
    document_id = int(cur.lastrowid)
    if keywords:
        conn.executemany(
            "INSERT INTO keywords (document_id, keyword, score) VALUES (?, ?, ?)",
            [(document_id, word, score) for word, score in keywords],
        )
    keyword_text = " ".join(word for word, _ in keywords)
    conn.execute(
        """
        INSERT INTO documents_fts (rowid, filename, full_text, keywords, category)
        VALUES (?, ?, ?, ?, ?)
        """,
        (document_id, filename, full_text or "", keyword_text, f"{category or ''} {subcategory or ''}".strip()),
    )
    conn.commit()
    return document_id


def _sanitize_fts_query(query: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch.isspace() or "\u0590" <= ch <= "\u05ff" else " "
        for ch in query
    )
    tokens = [tok for tok in cleaned.split() if tok]
    if not tokens:
        return ""
    return " AND ".join(f"{tok}*" for tok in tokens)


def _ocr_clause(ocr_states: list[str]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    if "native" in ocr_states:
        clauses.append("(d.is_scanned = 0 AND IFNULL(d.error, '') = '')")
    if "ocr" in ocr_states:
        clauses.append("d.is_scanned = 1")
    if "failed" in ocr_states:
        clauses.append("IFNULL(d.error, '') != ''")
    if not clauses:
        return "", []
    return "(" + " OR ".join(clauses) + ")", []


def _apply_filters(
    where: list[str],
    params: list[Any],
    *,
    categories: list[str] | None = None,
    subcategories: list[tuple[str, str]] | None = None,
    language: str | None = None,
    ocr_states: list[str] | None = None,
    folder: str | None = None,
) -> None:
    clauses: list[str] = []
    if categories:
        placeholders = ",".join("?" for _ in categories)
        clauses.append(f"d.category IN ({placeholders})")
        params.extend(categories)
    for parent, child in subcategories or []:
        clauses.append("(d.category = ? AND IFNULL(d.subcategory, '') = ?)")
        params.extend([parent, child])
    if clauses:
        where.append("(" + " OR ".join(clauses) + ")")
    if language:
        where.append("d.language = ?")
        params.append(language)
    clause, extra = _ocr_clause(ocr_states or [])
    if clause:
        where.append(clause)
        params.extend(extra)
    if folder:
        where.append("d.path LIKE ?")
        params.append(folder.rstrip("\\/") + "%")


def _order_sql(sort: str, fts_query: str) -> str:
    if sort == "name":
        return " ORDER BY d.filename COLLATE NOCASE"
    if sort == "modified":
        return " ORDER BY d.mtime DESC"
    if sort == "pages":
        return " ORDER BY d.page_count DESC"
    if fts_query:
        return " ORDER BY rank"
    return " ORDER BY d.indexed_at DESC"


def search_documents(
    conn: sqlite3.Connection,
    query: str = "",
    category: str | None = None,
    categories: list[str] | None = None,
    subcategories: list[tuple[str, str]] | None = None,
    language: str | None = None,
    ocr_states: list[str] | None = None,
    folder: str | None = None,
    sort: str = "relevance",
    limit: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    selected = list(categories or [])
    if category:
        selected.append(category)
    selected = [item for item in selected if item]
    sub_pairs = list(subcategories or [])

    where: list[str] = []
    params: list[Any] = []
    fts_query = _sanitize_fts_query(query) if query.strip() else ""

    if fts_query:
        from_sql = """
            FROM documents_fts
            JOIN documents d ON d.id = documents_fts.rowid
        """
        select_sql = """
            SELECT d.*, snippet(documents_fts, 1, '[[', ']]', '…', 24) AS snippet,
                   bm25(documents_fts) AS rank
        """
        where.append("documents_fts MATCH ?")
        params.append(fts_query)
    else:
        from_sql = " FROM documents d "
        select_sql = """
            SELECT d.*, substr(COALESCE(d.full_text, ''), 1, 240) AS snippet,
                   0 AS rank
        """

    _apply_filters(
        where,
        params,
        categories=selected,
        subcategories=sub_pairs,
        language=language,
        ocr_states=ocr_states,
        folder=folder,
    )
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    order_sql = _order_sql(sort, fts_query)

    try:
        match_count = int(conn.execute("SELECT COUNT(*) " + from_sql + where_sql, params).fetchone()[0])
        rows = conn.execute(
            select_sql + from_sql + where_sql + order_sql + " LIMIT ?",
            [*params, limit],
        ).fetchall()
    except sqlite3.OperationalError:
        like = f"%{query.strip()}%"
        from_sql = " FROM documents d "
        where = ["(d.filename LIKE ? OR d.full_text LIKE ? OR d.category LIKE ?)"]
        params = [like, like, like]
        _apply_filters(
            where,
            params,
            categories=selected,
            subcategories=sub_pairs,
            language=language,
            ocr_states=ocr_states,
            folder=folder,
        )
        where_sql = " WHERE " + " AND ".join(where)
        match_count = int(conn.execute("SELECT COUNT(*) " + from_sql + where_sql, params).fetchone()[0])
        rows = conn.execute(
            """
            SELECT d.*, substr(COALESCE(d.full_text, ''), 1, 240) AS snippet, 0 AS rank
            """
            + from_sql
            + where_sql
            + _order_sql(sort, "")
            + " LIMIT ?",
            [*params, limit],
        ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["keywords"] = [
            {"keyword": k["keyword"], "score": k["score"]}
            for k in conn.execute(
                "SELECT keyword, score FROM keywords WHERE document_id = ? ORDER BY score DESC",
                (item["id"],),
            ).fetchall()
        ]
        results.append(item)
    return results, match_count


def get_document(conn: sqlite3.Connection, document_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["keywords"] = [
        {"keyword": k["keyword"], "score": k["score"]}
        for k in conn.execute(
            "SELECT keyword, score FROM keywords WHERE document_id = ? ORDER BY score DESC",
            (document_id,),
        ).fetchall()
    ]
    return item


def category_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT COALESCE(category, 'אחר') AS category,
               IFNULL(subcategory, '') AS subcategory,
               COUNT(*) AS count
        FROM documents
        GROUP BY COALESCE(category, 'אחר'), IFNULL(subcategory, '')
        ORDER BY category, subcategory
        """
    ).fetchall()
    return [dict(row) for row in rows]


def update_document_classification(
    conn: sqlite3.Connection,
    document_id: int,
    category: str,
    subcategory: str = "",
) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE documents SET category = ?, subcategory = ? WHERE id = ?",
        (category, subcategory or "", document_id),
    )
    keyword_text = " ".join(
        k["keyword"]
        for k in conn.execute(
            "SELECT keyword FROM keywords WHERE document_id = ? ORDER BY score DESC",
            (document_id,),
        ).fetchall()
    )
    conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (document_id,))
    conn.execute(
        """
        INSERT INTO documents_fts (rowid, filename, full_text, keywords, category)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            document_id,
            row["filename"],
            row["full_text"] or "",
            keyword_text,
            f"{category} {subcategory or ''}".strip(),
        ),
    )
    conn.commit()
    return get_document(conn, document_id)


def rename_classification(
    conn: sqlite3.Connection,
    *,
    old_category: str,
    new_category: str,
    old_subcategory: str | None = None,
    new_subcategory: str | None = None,
) -> None:
    if old_subcategory is None:
        conn.execute(
            "UPDATE documents SET category = ? WHERE category = ?",
            (new_category, old_category),
        )
    else:
        conn.execute(
            """
            UPDATE documents
            SET category = ?, subcategory = ?
            WHERE category = ? AND IFNULL(subcategory, '') = ?
            """,
            (new_category, new_subcategory or "", old_category, old_subcategory),
        )
    conn.commit()


def clear_category_documents(conn: sqlite3.Connection, category_name: str, fallback: str = "אחר") -> None:
    conn.execute(
        "UPDATE documents SET category = ?, subcategory = '' WHERE category = ?",
        (fallback, category_name),
    )
    conn.commit()


def clear_subcategory_documents(
    conn: sqlite3.Connection,
    category_name: str,
    subcategory_name: str,
) -> None:
    conn.execute(
        """
        UPDATE documents
        SET subcategory = ''
        WHERE category = ? AND IFNULL(subcategory, '') = ?
        """,
        (category_name, subcategory_name),
    )
    conn.commit()


def document_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])


def language_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT COALESCE(language, 'unknown') AS language, COUNT(*) AS count
        FROM documents
        GROUP BY COALESCE(language, 'unknown')
        ORDER BY count DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def ocr_counts(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN is_scanned = 0 AND IFNULL(error, '') = '' THEN 1 ELSE 0 END) AS native,
            SUM(CASE WHEN is_scanned = 1 THEN 1 ELSE 0 END) AS ocr,
            SUM(CASE WHEN IFNULL(error, '') != '' THEN 1 ELSE 0 END) AS failed
        FROM documents
        """
    ).fetchone()
    return {
        "native": int(row["native"] or 0),
        "ocr": int(row["ocr"] or 0),
        "failed": int(row["failed"] or 0),
    }


def database_size() -> int:
    if not DB_PATH.exists():
        return 0
    return DB_PATH.stat().st_size


def clear_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM keywords")
    conn.execute("DELETE FROM documents")
    conn.execute("DELETE FROM documents_fts")
    conn.commit()
