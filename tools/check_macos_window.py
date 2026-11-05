"""Exercise the actual WebKit capsule and window with empty, disposable provider roots."""

import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch


def wait_for(condition, description):
    deadline = time.monotonic() + 12
    while not condition():
        if time.monotonic() >= deadline:
            raise AssertionError(description)
        time.sleep(0.1)


def main():
    if sys.platform != "darwin":
        raise SystemExit("This check needs a Mac desktop session.")
    import webview
    from trace_mechanism.workbench.desktop import launch

    errors = []
    start = webview.start

    def drive():
        window = webview.windows[0]
        try:
            # WebKit can report the first document load before ES modules bind
            # their controls or the workbench has opened its first panel.
            wait_for(
                lambda: window.run_js(
                    "Boolean(document.body.classList.contains('desktop') && "
                    "document.querySelector('#public-compact')?.onclick && "
                    "document.querySelector('#manage-prompts')?.getBoundingClientRect().width)"
                ),
                "Workbench controls did not become ready",
            )
            # run_js evaluates code directly; the workbench disallows eval().
            window.run_js("document.querySelector('#public-compact').click()")
            wait_for(lambda: window.width < 220, "Capsule did not collapse")
            window.run_js("document.querySelector('#capsule-open').click()")
            wait_for(lambda: window.width > 600, "Workbench did not reopen")
            window.run_js("document.querySelector('#public-float').click()")
            wait_for(lambda: window.on_top, "Float did not raise the workbench")
        except Exception as exc:
            errors.append(exc)
        finally:
            window.destroy()

    with tempfile.TemporaryDirectory(prefix="agent-trace-window-") as directory:
        home = Path(directory)
        env = {
            key: str(home / folder)
            for key, folder in (
                ("CODEX_HOME", "codex"),
                ("CLAUDE_CONFIG_DIR", "claude"),
                ("AGENT_TRACE_PROMPTS", "prompts"),
            )
        }
        with (
            patch.dict(os.environ, {**env, "HOME": directory}),
            patch.object(webview, "start", lambda **kw: start(drive, **kw)),
        ):
            launch()
    if errors:
        raise errors[0]
    print("Native capsule, window restoration and float passed.")


if __name__ == "__main__":
    main()
