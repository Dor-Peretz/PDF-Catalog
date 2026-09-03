# PDF Catalog

Local, offline catalog for PDF folders. It finds every PDF under a path, reads digital text or OCRs Hebrew/English scans, then stores keywords, categories, and dates in SQLite so you can search later. The web UI listens on `127.0.0.1` only.

## Requirements

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) with **Hebrew** and English data (needed for scanned PDFs)
- [Poppler](https://github.com/osberrysteve/poppler-windows) (`pdftoppm`) so scanned pages can be rendered

Install Tesseract and Poppler **once while you have internet**. After that the app does not need network access.

### Windows: Tesseract (Hebrew)

1. Download the Windows installer from [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki).
2. During setup, keep **Hebrew (`heb`)** and **English (`eng`)** selected under additional language data.
3. Default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
4. If you installed somewhere else, set `TESSERACT_CMD` to the `tesseract.exe` path.

### Windows: Poppler

1. Download a Poppler Windows build (for example from [osberrysteve/poppler-windows](https://github.com/osberrysteve/poppler-windows/releases)).
2. Unzip it, e.g. to `C:\poppler`.
3. Confirm `pdftoppm.exe` exists under `Library\bin` or `bin`.
4. If the app does not find it, set `POPPLER_PATH` to that `bin` folder.

Digital (text) PDFs still index without Tesseract/Poppler. Scans need both.

## Run

From this folder (no internet required after `pip install`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app
```

Open http://127.0.0.1:8765

1. Paste a folder path that contains PDFs.
2. Click **סרוק תיקייה**. Unchanged files (same SHA-256) are skipped.
3. Search by keyword, filter by category, and open the original file.

Metadata is stored in `data/catalog.db`. Nothing is uploaded.

## What is stored

- Path, filename, size, modified time, SHA-256
- Page count, OCR vs embedded text, detected language
- Full extracted text
- Keywords (Hebrew stopwords removed)
- Category: חשבונית, קבלה, חוזה, תעודה, מכתב, דוח, or אחר
- Dates found in the document
