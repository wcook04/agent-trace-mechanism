"""Exercise the actual WebKit capsule and window with empty, disposable provider roots."""

import argparse
import hashlib
import json
import os
import plistlib
from pathlib import Path
import shutil
import subprocess
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


def check_download(archive, receipt, screenshots, denied, interactions):
    """Observe the extracted application's fixture rows and optionally exercise controls through process-scoped Accessibility actions."""
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGWindowListOptionOnScreenOnly,
        kCGNullWindowID,
    )

    root = Path(__file__).resolve().parents[1]
    build = json.loads(receipt.read_text())
    if (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        != build["sha256"][archive.name]
    ):
        raise ValueError("Downloaded archive differs from the build receipt.")
    with tempfile.TemporaryDirectory(prefix="trace-package-") as tmp:
        scratch = Path(tmp).resolve()
        app = scratch / "Agent Trace Structurer.app"
        subprocess.run(["ditto", "-x", "-k", archive, scratch], check=True)
        embedded = json.loads(
            (app / "Contents/Resources/notices/build.json").read_text()
        )
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        assert (info["CFBundleShortVersionString"], info["CFBundleVersion"]) == (
            build["version"],
            build["build_number"],
        )
        assert all(
            embedded[key] == build[key]
            for key in ("revision", "version", "build_number")
        )
        driver = scratch / "exercise-window"
        if interactions:
            subprocess.run(
                ["swiftc", root / "tools/macos/exercise_window.swift", "-o", driver],
                check=True,
            )
        subprocess.run(["codesign", "--verify", "--deep", "--strict", app], check=True)
        policy = subprocess.run(
            ["spctl", "--assess", "--type", "execute", "-vv", app],
            text=True,
            capture_output=True,
            timeout=90,
        )
        print(
            "Gatekeeper assessment:",
            policy.returncode,
            policy.stderr.strip(),
            flush=True,
        )
        ocr = scratch / "read-window"
        subprocess.run(
            ["swiftc", root / "tools/macos/read_window_text.swift", "-o", ocr],
            check=True,
        )
        restricted = [root, Path.home() / ".codex", Path.home() / ".claude", *denied]
        rules = " ".join(
            "(subpath " + json.dumps(str(p.resolve())) + ")" for p in restricted
        )
        profile = "(version 1)(allow default)(deny file-read* " + rules + ")"
        for providers in ((), ("codex",), ("claude",), ("codex", "claude")):
            case = "-".join(providers) or "empty"
            home = scratch / case
            home.mkdir()
            for provider in providers:
                codex = provider == "codex"
                folder = home / (
                    "codex-root/sessions" if codex else "claude-root/projects"
                )
                if providers == ("codex",):
                    folder = folder.with_name("archived_sessions")
                folder.mkdir(parents=True)
                source = root / (
                    "examples/codex.jsonl" if codex else "tests/fixtures/claude.jsonl"
                )
                shutil.copyfile(source, folder / "source.jsonl")
                if codex:
                    (folder.parent / "session_index.jsonl").write_text(
                        json.dumps(
                            {
                                "id": "synthetic-codex",
                                "thread_name": "Old release notes",
                            }
                        )
                    )
            if len(providers) == 2:
                codex_dir = home / "codex-root/sessions"
                parent = codex_dir / "source.jsonl"
                fixtures = json.loads(parent.read_text().splitlines()[0])
                titles = {
                    "synthetic-codex": "Review the onboarding guide",
                    "example-reviewer": "Check setup examples",
                    "link-reviewer": "Verify reference links",
                }
                (codex_dir.parent / "session_index.jsonl").write_text(
                    "\n".join(
                        json.dumps({"id": sid, "thread_name": title})
                        for sid, title in titles.items()
                    )
                )
                for sid, nickname in (
                    ("example-reviewer", "Examples"),
                    ("link-reviewer", "References"),
                ):
                    worker = parent.read_text().splitlines()
                    worker[0] = json.dumps(
                        {
                            "type": "session_meta",
                            "payload": {
                                "id": sid,
                                "parent_thread_id": fixtures["payload"]["id"],
                                "agent_nickname": nickname,
                            },
                        }
                    )
                    (codex_dir / (sid + ".jsonl")).write_text("\n".join(worker) + "\n")
                lines = parent.read_text().splitlines()[:-1]
                lines[2] = json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "Review the onboarding guide and check its examples and references.",
                        },
                    }
                )
                latest = json.loads(lines[-1])
                latest["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                lines[-1] = json.dumps(latest)
                parent.write_text("\n".join(lines) + "\n")
            env = {
                k: os.environ[k]
                for k in (
                    "TMPDIR",
                    "LANG",
                    "USER",
                    "LOGNAME",
                    "__CF_USER_TEXT_ENCODING",
                )
                if k in os.environ
            }
            env.update(
                HOME=str(home),
                CFFIXED_USER_HOME=str(home),
                AGENT_TRACE_PROMPTS=str(home / "prompts"),
                PATH="/usr/bin:/bin",
                CODEX_HOME=str(home / "codex-root"),
                CLAUDE_CONFIG_DIR=str(home / "claude-root"),
            )
            snapshot = (screenshots or scratch) / ("workbench-" + case + ".png")
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            command = [
                "sandbox-exec",
                "-p",
                profile,
                app / "Contents/MacOS/Agent Trace Structurer",
            ]
            child = subprocess.Popen(command, cwd=home, env=env)
            try:

                def visible():
                    if child.poll() is not None:
                        raise RuntimeError(
                            f"Packaged app exited in {case}: {child.returncode}"
                        )
                    windows = CGWindowListCopyWindowInfo(
                        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
                    )
                    window_id = next(
                        (
                            w["kCGWindowNumber"]
                            for w in windows
                            if w["kCGWindowOwnerPID"] == child.pid
                            and w.get("kCGWindowName") == "Agent Trace Structurer"
                        ),
                        None,
                    )
                    if window_id is None:
                        return False
                    subprocess.run(
                        ["screencapture", "-x", "-l", str(window_id), snapshot],
                        check=True,
                    )
                    text = subprocess.check_output([ocr, snapshot], text=True).lower()
                    return (
                        (
                            (
                                "review the onboarding guide"
                                if len(providers) == 2
                                else "old release notes"
                            )
                            in text
                        )
                        == ("codex" in providers)
                        and ("read and update example.txt" in text)
                        == ("claude" in providers)
                        and (
                            providers != ("codex",)
                            or (
                                "archived in codex" in text
                                and "finished" in text
                                and "retired" not in text
                            )
                        )
                        and (bool(providers) or ("find your conversations" in text and "history folders" in text))
                    )

                wait_for(visible, f"Expected fixture rows did not appear in {case}")
                if interactions and len(providers) == 2:

                    def control(action, element, *args):
                        return subprocess.check_output(
                            [driver, str(child.pid), action, element, *args], text=True
                        ).strip()

                    control("press", "public-float")
                    wait_for(
                        lambda: control("value", "public-float") == "1", "Float failed"
                    )
                    control("press", "public-float")
                    control("press", "public-compact")
                    control("press", "capsule-open")
                    control("present", "mission-pane-refresh")
                    control("press", "choose-sources")
                    control("press", "source-preview")
                    control("present", "preview-copy")
                    arrival = "Live review completed after preview."
                    with parent.open("a") as log:
                        log.write(
                            json.dumps(
                                {
                                    "type": "event_msg",
                                    "payload": {
                                        "type": "task_complete",
                                        "last_agent_message": arrival,
                                    },
                                }
                            )
                            + "\n"
                        )
                    control("press", "preview-copy")
                    wait_for(
                        lambda: (
                            "Review the onboarding guide"
                            in subprocess.check_output(["pbpaste"], text=True)
                        ),
                        "Captured parent missing from native pasteboard",
                    )
                    assert arrival not in subprocess.check_output(
                        ["pbpaste"], text=True
                    )
                    control("press", "mission-pane-copy-capsule")
                    wait_for(
                        lambda: (
                            arrival in subprocess.check_output(["pbpaste"], text=True)
                        ),
                        "Refresh did not copy the live arrival",
                    )
                    control("press", "manage-prompts")
                    control("set", "prompt-name", "review")
                    control(
                        "set",
                        "prompt-md",
                        "# Review notes\nUse only the selected evidence.",
                    )
                    control("press", "prompt-save")
                    wait_for(
                        lambda: (home / "prompts/review.md").exists(),
                        "Native prompt save failed",
                    )
                    child.terminate()
                    child.wait(timeout=10)
                    child = subprocess.Popen(command, cwd=home, env=env)
                    control("press", "button:Review notes")
                    wait_for(
                        lambda: (
                            "Use only the selected evidence."
                            in subprocess.check_output(["pbpaste"], text=True)
                        ),
                        "Saved prompt unavailable after native relaunch",
                    )
                print(
                    f"{case}: packaged window displayed the expected histories.",
                    flush=True,
                )
            finally:
                child.terminate()
                child.wait(timeout=10)


def main():
    if sys.platform != "darwin":
        raise SystemExit("This check needs a Mac desktop session.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Exercise a downloaded Mac ZIP with four provider profiles",
    )
    parser.add_argument(
        "--receipt", type=Path, help="Build receipt (default: beside the archive)"
    )
    parser.add_argument(
        "--screenshots", type=Path, help="Keep the four packaged-window screenshots"
    )
    parser.add_argument(
        "--deny-read",
        type=Path,
        action="append",
        default=[],
        help="Additional checkout to deny the app",
    )
    parser.add_argument(
        "--interactions",
        action="store_true",
        help="Press controls in the extracted app using an already authorized Accessibility test driver",
    )
    args = parser.parse_args()
    if args.archive:
        return check_download(
            args.archive,
            args.receipt or args.archive.with_name("build-receipt.json"),
            args.screenshots,
            args.deny_read,
            args.interactions,
        )
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
