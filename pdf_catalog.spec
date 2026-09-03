from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

project = Path(SPECPATH)
tess_src = Path(r"C:\Program Files\Tesseract-OCR")
icon_file = str(project / "build" / "icon.ico")

datas = [
    (str(project / "web"), "web"),
    (str(project / "data" / "hebrew_stopwords.txt"), "data"),
    (str(project / "data" / "tessdata"), "data/tessdata"),
]
binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "app",
    "app.main",
    "app.db",
    "app.scanner",
    "app.keywords",
    "app.pdf_extract",
    "app.settings",
    "app.fs",
    "app.paths",
]

if tess_src.exists():
    binaries.append((str(tess_src / "tesseract.exe"), "tesseract"))
    for dll in tess_src.glob("*.dll"):
        binaries.append((str(dll), "tesseract"))

for package in ("uvicorn", "fastapi", "starlette", "anyio", "pymupdf", "pypdf", "PIL"):
    collected_datas, collected_binaries, collected_hidden = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hidden
    binaries += collect_dynamic_libs(package)

a = Analysis(
    [str(project / "run_app.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PDF-Catalog",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file if Path(icon_file).exists() else None,
)
