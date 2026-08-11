"""
Development server.

Serves ``dist/`` over HTTP with two conveniences the real host does not need:

* **Rebuild on navigation.**  Before serving an HTML request, the server checks
  whether any source file changed since the last build and rebuilds if so.  No
  file watcher, no polling thread -- the reload you were about to do anyway is
  the trigger.
* **Header parity.**  It sends the same security headers the production CSP
  meta tag declares, so a policy violation shows up here rather than after a
  deploy.

Bound to 127.0.0.1 by default.  This serves a directory over HTTP with no
authentication; do not expose it.
"""

from __future__ import annotations

import http.server
import os
import socketserver
import sys
import threading
import time
from typing import Callable

__all__ = ["serve"]


WATCH_SUFFIXES = (".md", ".html", ".css", ".js", ".mjs", ".json", ".py", ".svg", ".webmanifest")
IGNORE_DIRS = {".git", "dist", "__pycache__", ".claude", "node_modules"}


def _newest_mtime(root: str) -> float:
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_DIRS and not name.startswith(".")]
        for filename in filenames:
            if not filename.endswith(WATCH_SUFFIXES):
                continue
            try:
                stamp = os.path.getmtime(os.path.join(dirpath, filename))
            except OSError:
                continue
            if stamp > newest:
                newest = stamp
    return newest


class _Handler(http.server.SimpleHTTPRequestHandler):
    directory_root = "."
    source_root = "."
    rebuild: Callable[[], str | None] | None = None
    csp = ""
    permissions_policy = ""
    _lock = threading.Lock()
    _last_build = 0.0
    _last_error: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=self.directory_root, **kwargs)

    # -- rebuild ---------------------------------------------------------- #

    def _maybe_rebuild(self) -> None:
        if self.rebuild is None:
            return
        newest = _newest_mtime(self.source_root)
        with _Handler._lock:
            if newest <= _Handler._last_build:
                return
            started = time.perf_counter()
            error = self.rebuild()
            _Handler._last_build = time.time()
            _Handler._last_error = error
            elapsed = (time.perf_counter() - started) * 1000
            if error:
                sys.stderr.write(f"\n  rebuild failed: {error}\n")
            else:
                sys.stderr.write(f"  rebuilt in {elapsed:.0f} ms\n")

    # -- request handling ------------------------------------------------- #

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        if self.path.split("?")[0].rstrip("/").endswith((".html", "")) or "." not in os.path.basename(self.path.split("?")[0]):
            self._maybe_rebuild()
        if _Handler._last_error and self.path.endswith(("/", ".html")):
            self._send_build_error()
            return
        super().do_GET()

    def _send_build_error(self) -> None:
        body = (
            "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            "<title>build error</title><style>body{background:#0a0c10;color:#ff5f56;"
            "font:14px/1.6 ui-monospace,monospace;padding:3rem}pre{white-space:pre-wrap}</style>"
            "</head><body><h1>build fallido</h1><pre>"
            + (_Handler._last_error or "").replace("<", "&lt;")
            + "</pre><p>Corrige el error y recarga.</p></body></html>"
        ).encode("utf-8")
        self.send_response(500)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Mirror what a properly configured host would send. GitHub Pages
        # cannot set these, which is why the site also carries a CSP meta tag.
        if self.csp:
            self.send_header("Content-Security-Policy", self.csp)
        if self.permissions_policy:
            self.send_header("Permissions-Policy", self.permissions_policy)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path):  # type: ignore[override]
        mapping = {
            ".webmanifest": "application/manifest+json",
            ".mjs": "text/javascript",
            ".js": "text/javascript",
            ".xml": "application/xml",
            ".webp": "image/webp",
            ".avif": "image/avif",
            ".woff2": "font/woff2",
            ".asc": "text/plain",
        }
        extension = os.path.splitext(path)[1].lower()
        if extension in mapping:
            return mapping[extension]
        return super().guess_type(path)

    def log_message(self, fmt: str, *args) -> None:
        status = str(args[1]) if len(args) > 1 else ""
        colour = "\033[38;5;46m" if status.startswith("2") else "\033[38;5;220m" if status.startswith("3") else "\033[38;5;196m"
        sys.stderr.write(f"  {colour}{status}\033[0m  {args[0] if args else ''}\n")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(config, *, host: str = "127.0.0.1", port: int = 8000, rebuild: Callable[[], str | None] | None = None) -> None:
    _Handler.directory_root = config.output_path
    _Handler.source_root = config.source_root
    _Handler.rebuild = staticmethod(rebuild) if rebuild else None
    _Handler.csp = config.csp_header()
    _Handler.permissions_policy = config.permissions_policy
    _Handler._last_build = time.time()

    try:
        server = _Server((host, port), _Handler)
    except OSError as error:
        print(f"cannot bind {host}:{port} -- {error}", file=sys.stderr)
        raise SystemExit(1) from error

    url = f"http://{host}:{port}/"
    print(f"\n  \033[38;5;46mserving\033[0m  {config.output_path}")
    print(f"  \033[38;5;46m→\033[0m        {url}")
    print("  Ctrl+C para parar\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  detenido\n")
    finally:
        server.server_close()
