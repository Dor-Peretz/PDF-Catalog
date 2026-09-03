from __future__ import annotations

import logging
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from app.paths import is_frozen, user_data_dir, web_dir

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _setup_stdio() -> None:
    log_dir = user_data_dir()
    if sys.stdout is None:
        sys.stdout = open(log_dir / "stdout.log", "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(log_dir / "stderr.log", "a", encoding="utf-8")


def _setup_logging() -> None:
    log_file = user_data_dir() / "pdf-catalog.log"
    logging.basicConfig(
        filename=str(log_file),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if not is_frozen():
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        logging.getLogger().addHandler(console)


def _free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    return start


def main() -> None:
    multiprocessing.freeze_support()
    _setup_stdio()
    _setup_logging()
    os.chdir(user_data_dir())
    from app.main import app

    port = int(os.environ.get("PDF_CATALOG_PORT", _free_port()))
    url = f"http://{HOST}:{port}"
    app.state.public_url = url
    logging.getLogger(__name__).info(
        "Starting PDF Catalog at %s (frozen=%s web=%s)",
        url,
        is_frozen(),
        web_dir(),
    )

    def open_browser() -> None:
        time.sleep(0.7)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", loop="asyncio")
    uvicorn.Server(config).run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("PDF Catalog failed to start")
        if not is_frozen():
            raise
        sys.exit(1)
