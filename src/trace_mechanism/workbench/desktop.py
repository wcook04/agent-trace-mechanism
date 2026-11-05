"""macOS window and pasteboard for the portable workbench."""

from pathlib import Path
import sys
import tempfile
import threading
from .server import start


def launch():
    if sys.platform != "darwin":
        raise SystemExit(
            "Use agent-trace-app for the browser workbench on this platform."
        )
    try:
        import webview
        from AppKit import (
            NSPasteboard,
            NSPasteboardTypeString,
            NSWorkspace,
            NSFloatingWindowLevel,
            NSWindowStyleMaskBorderless,
            NSAnimationContext,
        )
        from Foundation import NSOperationQueue, NSMakeRect
    except ImportError as exc:
        raise SystemExit(
            "Install the desktop extra: python -m pip install '.[desktop]'"
        ) from exc
    server, url = start()

    class Native:
        def copy(self, text):
            pb = NSPasteboard.generalPasteboard()
            pb.clearContents()
            if not pb.setString_forType_(text, NSPasteboardTypeString):
                raise RuntimeError("Clipboard refused the copy.")
            return "Copied"

        def save(self, text):
            directory = Path.home() / "Downloads"
            directory.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix="Agent Trace ",
                suffix=".txt",
                delete=False,
            ) as f:
                f.write(text)
            NSWorkspace.sharedWorkspace().selectFile_inFileViewerRootedAtPath_(
                f.name, ""
            )
            return "Saved and revealed"

        def capsule(self, mode):
            if mode not in ("compact", "hover", "leave", "window"):
                raise ValueError("Unknown window mode.")

            def apply():
                n = window.native
                if mode == "compact" and not getattr(self, "_saved", None):
                    self._saved = (n.frame(), n.styleMask(), n.level(), n.minSize())
                    n.setMinSize_((46, 46))
                    n.setStyleMask_(NSWindowStyleMaskBorderless)
                    n.setLevel_(NSFloatingWindowLevel)
                if not getattr(self, "_saved", None):
                    return
                if mode == "window":
                    frame, style, level, minimum = self._saved
                    self._saved = None
                    n.setStyleMask_(style)
                    n.setLevel_(level)
                    n.setMinSize_(minimum)
                else:
                    visible = n.screen().visibleFrame()
                    width = 152 if mode == "hover" else 52
                    frame = NSMakeRect(
                        visible.origin.x + (visible.size.width - width) / 2,
                        visible.origin.y + visible.size.height - 58,
                        width,
                        48,
                    )
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(
                    0
                    if NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion()
                    else 0.18
                )
                n.animator().setFrame_display_(frame, True)
                NSAnimationContext.endGrouping()

            NSOperationQueue.mainQueue().addOperationWithBlock_(apply)
            return mode

        def floating(self, enabled):
            window.on_top = bool(enabled)
            return window.on_top

    bridge = Native()
    server.desktop = {
        "copy": bridge.copy,
        "save": bridge.save,
        "floating": bridge.floating,
        "capsule": bridge.capsule,
    }
    with server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            window = webview.create_window(
                "Agent Trace Structurer",
                url,
                width=1340,
                height=820,
                min_size=(620, 440),
                background_color="#14171c",
            )
            webview.start(private_mode=True)
        finally:
            server.shutdown()
            thread.join()
