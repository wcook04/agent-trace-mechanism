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
from ..agent_tools import SnapshotStore

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
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; connect-src 'self'",
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
            asset = file.read_bytes()
            if path == "/" and s.desktop:
                asset = asset.replace(
                    b"<head>",
                    b'<head><meta name="agent-trace-desktop" content="true">',
                    1,
                )
            return self.reply(200, asset, MIME.get(file.suffix, "text/javascript"))
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
                elif path == "/capture-options":
                    with s.refresh:
                        lib.discover()
                        result = lib.capture_options(body)
                elif path == "/trace":
                    with s.refresh:
                        lib.discover()
                    result = lib.trace(body)
                    if body.get("preview") and s.desktop:
                        handle = secrets.token_urlsafe(24)
                        s.previews[handle] = result
                        result["preview_handle"] = handle
                    delivery = body.get("deliver")
                    if delivery in ("copy", "save") and s.desktop:
                        result["verb"] = s.desktop[delivery](result.pop("text"))
                elif path == "/copy-preview" and s.desktop:
                    capture = s.previews.get(body.get("preview_handle"))
                    if capture is None or capture["text_sha256"] != body.get("sha256"):
                        raise ValueError("This preview expired. Open the preview again.")
                    result = {"verb": s.desktop["copy"](capture["text"])}
                elif path == "/preview-prompt":
                    raw = body.get("raw")
                    if not isinstance(raw, str) or len(raw.encode()) > shelf.LIMIT:
                        raise ValueError("Enter up to 1 MiB of Markdown.")
                    result = {"text": shelf.describe("draft", raw, user=True)["body"]}
                elif path == "/window" and s.desktop:
                    action = body.get("action")
                    if action not in s.desktop:
                        raise ValueError("Unknown window action.")
                    result = {"value": s.desktop[action](body.get("value"))}
                elif path == "/history-folders":
                    homes = {}
                    for provider in ("codex", "claude"):
                        value = body.get(provider, "")
                        if not isinstance(value, str):
                            raise ValueError("Enter an absolute provider home directory.")
                        if value.strip():
                            folder = Path(value.strip()).expanduser()
                            if not folder.is_absolute() or not folder.is_dir():
                                raise ValueError(f"The {provider} home must be an existing absolute directory.")
                            homes[provider] = str(folder.resolve())
                    with s.refresh:
                        save_settings(marker_path().with_name("history-folders.json"), homes)
                        s.library = Library(homes)
                        s.folder_notice = ""
                    result = {"ok": True}
                elif path == "/marker":
                    with s.shelf_lock:
                        markers = read_markers(s, writing=True)
                        key = body.get("mission_key")
                        if (
                            not isinstance(key, str)
                            or not key.startswith(
                                ("codex:", "claude_code:", "claude:", "file:")
                            )
                            or len(key) > 1024
                        ):
                            raise ValueError("Invalid mission key.")
                        if body.get("clear"):
                            markers.pop(key, None)
                        else:
                            markers[key] = body
                        save_settings(marker_path(), markers)
                    result = {"ok": True}
                elif path == "/remove-prompt":
                    with s.shelf_lock:
                        result = shelf.remove(body.get("slug"), body.get("revision"))
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
                    discovery, conflicts = lib.discovery, len(lib.conflicts)
                with s.shelf_lock:
                    markers = read_markers(s)
                    notice = s.marker_notice
                    changed = False
                    for row in rows:
                        key = "file:" + row["ref"]
                        old = f"{row['provider']}:{row['session_id']}"
                        if not row["ambiguous"] and old in markers and key not in markers:
                            markers[key] = dict(markers.pop(old), mission_key=key)
                            changed = True
                    if changed:
                        save_settings(marker_path(), markers)
                result = dict(
                    ok=True,
                    index=dict(
                        marker_notice=notice or s.folder_notice,
                        folder_settings=lib.homes,
                        discovery=discovery,
                        active_rows=rows,
                        ambiguous_sessions=conflicts,
                        inactive_rows=[],
                        generated_at=iso(time.time()),
                        operator_markers=markers,
                    ),
                )
            elif path == "/catalogue":
                with lib.lock:
                    rows = list(lib.entries.values())
                q = parse_qs(urlsplit(self.path).query).get("q", [""])[0].casefold()
                hits = [
                    {"session_id": e["session_id"]}
                    for e in rows
                    if q in (e["source_title"] or e["prompt_derived_title"]).casefold()
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
        except (
            OSError,
            KeyError,
            ValueError,
            TypeError,
            RuntimeError,
            AttributeError,
        ) as exc:
            self.reply(400, {"ok": False, "error": str(exc)})

    do_GET = do_POST = route


def marker_path():
    return Path.home() / ".agent-trace" / "mission-markers.json"


def save_settings(path, values):
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Settings location is a symbolic link.")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(values, stream)
    os.replace(stream.name, path)


def read_markers(server, writing=False):
    path = marker_path()
    server.marker_notice = ""
    try:
        if path.is_symlink() or path.parent.is_symlink():
            raise OSError("The preferences location is a symbolic link.")
        try:
            markers = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(markers, dict) or any(
                not isinstance(m, dict) for m in markers.values()
            ):
                raise ValueError("Invalid marker format")
            return markers
        except (ValueError, RecursionError):
            backup = path.with_name(f"{path.stem}.damaged-{secrets.token_hex(6)}.json")
            path.rename(backup)
            server.marker_notice = f"Pin and archive settings could not be read. The original was saved at {backup}."
    except FileNotFoundError:
        pass
    except OSError as exc:
        server.marker_notice = f"Pin and archive settings are unavailable: {exc}"
        if writing:
            raise ValueError(server.marker_notice) from exc
    return {}


def start():
    s = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    path = marker_path().with_name("history-folders.json")
    s.folder_notice = ""
    try:
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Settings path is a symbolic link.")
        homes = json.loads(path.read_text())
        if not isinstance(homes, dict) or any(k not in ("codex", "claude") or not isinstance(v, str) or not Path(v).is_absolute() for k, v in homes.items()):
            raise ValueError("Invalid provider directories.")
    except FileNotFoundError:
        homes = {}
    except (OSError, ValueError, RecursionError):
        homes = {}
        s.folder_notice = "Saved history folders could not be read. Open History folders to choose them again."
    s.library = Library(homes)
    s.marker_notice = ""
    s.desktop = None
    s.token = secrets.token_urlsafe(32)
    s.authority = "127.0.0.1:" + str(s.server_port)
    s.origin = "http://" + s.authority
    s.refresh = threading.Lock()
    s.shelf_lock = threading.Lock()
    s.previews = SnapshotStore(max_count=16)
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
