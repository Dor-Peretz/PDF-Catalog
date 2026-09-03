from __future__ import annotations

from pathlib import Path

from app import db
from app.scanner import reindex_path


def main() -> None:
    conn = db.init_db()
    rows = conn.execute(
        "SELECT id, path, filename FROM documents WHERE IFNULL(error,'') != '' ORDER BY id"
    ).fetchall()
    conn.close()
    print(f"reindexing {len(rows)} files", flush=True)
    ok = fail = 0
    for index, row in enumerate(rows, start=1):
        path = Path(row["path"])
        print(f"[{index}/{len(rows)}] {row['filename']}", flush=True)
        if not path.exists():
            print("  MISSING", flush=True)
            fail += 1
            continue
        try:
            reindex_path(path)
            conn = db.get_connection()
            doc = db.find_by_path(conn, str(path.resolve()))
            conn.close()
            error = doc["error"] if doc else "not saved"
            text_len = len(doc["full_text"] or "") if doc else 0
            scanned = doc["is_scanned"] if doc else 0
            if error:
                print(f"  FAIL {error[:180]} chars={text_len}", flush=True)
                fail += 1
            else:
                print(f"  OK scanned={scanned} chars={text_len}", flush=True)
                ok += 1
        except Exception as exc:
            print(f"  EXC {exc}", flush=True)
            fail += 1
    conn = db.init_db()
    print(f"done ok={ok} fail={fail} counts={db.ocr_counts(conn)}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
