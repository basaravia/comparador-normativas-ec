#!/usr/bin/env python3
"""Servidor HTTP multihilo ligero para servir la SPA de Vue 3 en el puerto 8000 con fallback a index.html.
"""
from __future__ import annotations

import http.server
import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ui_server")

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "frontend" / "dist"


class SPAHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def do_GET(self):
        # Si la ruta no corresponde a un archivo físico existente (ej. js, css, assets),
        # sirve index.html para soportar enrutamiento del lado del cliente (SPA)
        path = self.translate_path(self.path)
        if not os.path.exists(path) or os.path.isdir(path):
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, format, *args):
        # Suprimir logs ruidosos de estáticos
        pass


def run_server(host: str = "127.0.0.1", port: int = 8000):
    if not DIST_DIR.exists():
        raise FileNotFoundError(f"El directorio dist {DIST_DIR} no existe. Ejecute 'npm run build' primero.")

    logger.info("Iniciando servidor de UI SPA en http://%s:%d sirviendo %s", host, port, DIST_DIR)
    server = http.server.ThreadingHTTPServer((host, port), SPAHTTPRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Servidor detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
