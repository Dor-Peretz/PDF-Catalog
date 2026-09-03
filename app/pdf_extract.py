from __future__ import annotations

import io
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pymupdf
from pypdf import PdfReader

MIN_CHARS_PER_PAGE = 30
OCR_DPI = 200
OCR_LANG = "heb+eng"

ROOT = Path(__file__).resolve().parent.parent
LOCAL_TESSDATA = ROOT / "data" / "tessdata"


def _windows_program_files() -> list[Path]:
    paths = []
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        value = os.environ.get(key)
        if value:
            paths.append(Path(value))
    paths.append(Path(r"C:\Program Files"))
    paths.append(Path(r"C:\Program Files (x86)"))
    return paths


def find_tesseract() -> str | None:
    env = os.environ.get("TESSERACT_CMD") or os.environ.get("TESSERACT_PATH")
    if env and Path(env).exists():
        return env
    which = shutil.which("tesseract")
    if which:
        return which
    for root in _windows_program_files():
        candidate = root / "Tesseract-OCR" / "tesseract.exe"
        if candidate.exists():
            return str(candidate)
    return None


def find_poppler() -> str | None:
    env = os.environ.get("POPPLER_PATH")
    if env and Path(env).exists():
        return env
    for root in _windows_program_files() + [Path(r"C:\poppler"), Path(r"C:\tools")]:
        for candidate in (
            root / "poppler" / "Library" / "bin",
            root / "poppler" / "bin",
            root / "Library" / "bin",
        ):
            if (candidate / "pdftoppm.exe").exists() or (candidate / "pdftoppm").exists():
                return str(candidate)
        if root.exists():
            for match in root.glob("poppler*/Library/bin"):
                if (match / "pdftoppm.exe").exists():
                    return str(match)
            for match in root.glob("poppler*/bin"):
                if (match / "pdftoppm.exe").exists():
                    return str(match)
    which = shutil.which("pdftoppm")
    if which:
        return str(Path(which).parent)
    return None


def find_tessdata() -> Path | None:
    env = os.environ.get("TESSDATA_PREFIX")
    candidates = []
    if env:
        candidates.append(Path(env))
        candidates.append(Path(env) / "tessdata")
    candidates.append(LOCAL_TESSDATA)
    tesseract = find_tesseract()
    if tesseract:
        candidates.append(Path(tesseract).parent / "tessdata")
    for folder in candidates:
        if (folder / "heb.traineddata").exists() and (folder / "eng.traineddata").exists():
            return folder
    for folder in candidates:
        if folder.exists() and any(folder.glob("*.traineddata")):
            return folder
    return None


def configure_ocr() -> tuple[str | None, str | None]:
    tesseract = find_tesseract()
    poppler = find_poppler()
    if tesseract:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = tesseract
    return tesseract, poppler


def ocr_config(lang: str = OCR_LANG) -> tuple[str, str]:
    tessdata = find_tessdata()
    if tessdata:
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    config = "--psm 6"
    if tessdata:
        config = f"--psm 6 --tessdata-dir {str(tessdata)}"
    available = set()
    if tessdata:
        available = {path.stem for path in tessdata.glob("*.traineddata")}
    wanted = [part for part in (lang or OCR_LANG).split("+") if part]
    use = [part for part in wanted if not available or part in available]
    if not use:
        use = ["eng"] if "eng" in available or not available else [name for name in available if name != "osd"][:1]
    return "+".join(use) or "eng", config


def _letter_count(text: str) -> int:
    return sum(1 for ch in text if ch.isalpha())


def needs_ocr(text: str, page_count: int) -> bool:
    pages = max(page_count, 1)
    return _letter_count(text) < MIN_CHARS_PER_PAGE * pages


def extract_embedded_text(path: Path) -> tuple[str, int]:
    try:
        doc = pymupdf.open(path)
        try:
            parts = [(page.get_text("text") or "") for page in doc]
            return "\n".join(parts).strip(), doc.page_count
        finally:
            doc.close()
    except Exception:
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        parts: list[str] = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        return "\n".join(parts).strip(), pages


def _pixmap_to_image(pix):
    from PIL import Image

    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def ocr_with_pymupdf(path: Path, lang: str, config: str) -> tuple[str, int]:
    import pytesseract

    doc = pymupdf.open(path)
    try:
        texts: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=OCR_DPI, alpha=False)
            image = _pixmap_to_image(pix)
            texts.append(pytesseract.image_to_string(image, lang=lang, config=config))
        return "\n".join(texts).strip(), doc.page_count
    finally:
        doc.close()


def ocr_with_poppler(path: Path, poppler_path: str | None, lang: str, config: str) -> tuple[str, int]:
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(str(path), dpi=OCR_DPI, poppler_path=poppler_path)
    texts = [pytesseract.image_to_string(image, lang=lang, config=config) for image in images]
    return "\n".join(texts).strip(), len(images)


def ocr_pdf(path: Path, poppler_path: str | None = None, lang: str = OCR_LANG) -> tuple[str, int]:
    use_lang, config = ocr_config(lang)
    try:
        return ocr_with_pymupdf(path, use_lang, config)
    except Exception:
        if not poppler_path:
            poppler_path = find_poppler()
        if not poppler_path:
            raise
        return ocr_with_poppler(path, poppler_path, use_lang, config)


def extract_pdf(
    path: Path,
    *,
    run_ocr: bool = True,
    ocr_lang: str = OCR_LANG,
    on_stage: Callable[[str], None] | None = None,
) -> dict:
    def stage(name: str) -> None:
        if on_stage:
            on_stage(name)

    tesseract, poppler = configure_ocr()
    error = None
    is_scanned = False
    text = ""
    page_count = 0

    try:
        stage("Reading PDF")
        text, page_count = extract_embedded_text(path)
        stage("Extracting text")
    except Exception as exc:
        error = f"PDF read failed: {exc}"
        text = ""
        page_count = 0

    if run_ocr and needs_ocr(text, page_count):
        if not tesseract:
            error = "Tesseract OCR is not installed (needed for scanned PDFs)."
        else:
            try:
                stage("OCR")
                text, page_count = ocr_pdf(path, poppler, ocr_lang)
                is_scanned = True
                error = None
            except Exception as exc:
                error = f"OCR failed: {exc}"

    return {
        "text": text,
        "page_count": page_count,
        "is_scanned": is_scanned,
        "error": error,
        "tesseract": tesseract,
        "poppler": poppler,
    }


def ocr_status() -> dict[str, str | None | bool]:
    tesseract, poppler = configure_ocr()
    tessdata = find_tessdata()
    has_hebrew = bool(tessdata and (tessdata / "heb.traineddata").exists())
    renderer = True
    return {
        "tesseract": tesseract,
        "poppler": poppler,
        "tessdata": str(tessdata) if tessdata else None,
        "hebrew": has_hebrew,
        "ready": bool(tesseract and renderer),
    }
