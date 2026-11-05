"""Token-protected local transport for the Agent Trace Structurer workbench."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import os
import tempfile
import time
from .library import iso
import threading
from urllib.parse import urlsplit, parse_qs, unquote
import webbrowser
from . import shelf
from .library import Library

ASSETS = {
    "/": "index.html",
    "/app.mjs": "app.mjs",
    "/portable.mjs": "portable.mjs",
    "/lifecycle_reducer.mjs": "lifecycle_reducer.mjs",
}
MIME = {".html": "text/html", ".mjs": "text/javascript"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, mime="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        for key, value in {
            "Content-Type": mime + "; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            "Content-Length": str(len(body)),
        }.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        s = self.server
        if self.headers.get("Host") != s.authority:
            return self.reply(403, {})
        path = urlsplit(self.path).path
        if self.command == "GET" and (
            path in ASSETS or path in ("/parser.mjs", "/key.js")
        ):
            file = Path(__file__).parent
            file = (
                file.parent / "structurer.mjs"
                if path == "/parser.mjs"
                else file / ("key.js" if path == "/key.js" else ASSETS[path])
            )
            return self.reply(
                200, file.read_bytes(), MIME.get(file.suffix, "text/javascript")
            )
        if self.headers.get(
            "Origin", s.origin
        ) != s.origin or not secrets.compare_digest(
            self.headers.get("X-Agent-Trace-Key", "").encode(), s.token.encode()
        ):
            return self.reply(401, {})
        try:
            lib = s.library
            if self.command == "POST":
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 6 * shelf.LIMIT + 1024:
                    return self.reply(413, {})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected an object.")
                if path == "/activity":
                    result = lib.activity(body)
                elif path == "/trace":
                    result = lib.trace(body)
                elif path == "/marker":
                    with s.shelf_lock:
                        markers = read_markers()
                        key = body.get("mission_key")
                        if (
                            not isinstance(key, str)
                            or not key.startswith(("codex:", "claude_code:", "claude:"))
                            or len(key) > 1024
                        ):
                            raise ValueError("Invalid mission key.")
                        if body.get("clear"):
                            markers.pop(key, None)
                        else:
                            markers[key] = body
                        folder = marker_path().parent
                        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                        with tempfile.NamedTemporaryFile(
                            mode="w", dir=folder, delete=False
                        ) as f:
                            json.dump(markers, f)
                        os.replace(f.name, marker_path())
                    result = {"ok": True}
                elif path == "/save-prompt":
                    with s.shelf_lock:
                        result = shelf.save(
                            body.get("slug"), body.get("raw"), body.get("revision")
                        )
                else:
                    return self.reply(404, {})
            elif path == "/mission-index":
                with s.refresh:
                    rows = lib.discover()
                result = dict(
                    ok=True,
                    index=dict(
                        active_rows=rows,
                        inactive_rows=[],
                        generated_at=iso(time.time()),
                        operator_markers=read_markers(),
                    ),
                )
            elif path == "/catalogue":
                with lib.lock:
                    rows = list(lib.entries.values())
                q = parse_qs(urlsplit(self.path).query).get("q", [""])[0].casefold()
                hits = [
                    {"session_id": e["session_id"]}
                    for e in rows
                    if q in e["source_title"].casefold()
                ]
                result = dict(
                    ok=True,
                    counts=dict(catalogued=len(rows), candidates=len(rows)),
                    total_matching=len(hits),
                    entries=hits[:400],
                )
            elif path == "/prompt-shelf":
                result = dict(
                    ok=True,
                    items=[dict(item, slot=item["slug"]) for item in shelf.listing()],
                    directory=str(shelf.user_dir()),
                )
            elif path.startswith("/prompt-shelf/"):
                item = shelf.read(unquote(path[len("/prompt-shelf/") :]))
                if not item:
                    return self.reply(404, {"error": "Prompt no longer exists."})
                result = dict(ok=True, **item)
            else:
                return self.reply(404, {})
            return self.reply(200, result)
        except (OSError, KeyError, ValueError, TypeError, RuntimeError) as exc:
            self.reply(400, {"ok": False, "error": str(exc)})

    do_GET = do_POST = route


def marker_path():
    return Path.home() / ".agent-trace" / "mission-markers.json"


def read_markers():
    try:
        return json.loads(marker_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def start():
    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    s.library = Library()
    s.token = secrets.token_urlsafe(32)
    s.authority = "127.0.0.1:" + str(s.server_port)
    s.origin = "http://" + s.authority
    s.refresh = threading.Lock()
    s.shelf_lock = threading.Lock()
    return s, s.origin + "/#k=" + s.token


def main():
    parser = argparse.ArgumentParser(
        description="Open the Agent Trace Structurer workbench."
    )
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--desktop",
        action="store_true",
        help="Open a native macOS window (desktop extra).",
    )
    parser.add_argument("--prompts-dir", action="store_true")
    args = parser.parse_args()
    if args.prompts_dir:
        print(shelf.user_dir())
        return
    if args.desktop:
        from .desktop import launch

        launch()
        return
    s, url = start()
    with s:
        print(url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            s.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
