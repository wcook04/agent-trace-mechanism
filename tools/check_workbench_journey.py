"""Exercise a real browser clipboard and optionally a fresh Claude Code MCP session."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def fresh_agent(python, home, manifest, sid, expected):
    config = {
        "mcpServers": {
            "agent-trace": {
                "command": python,
                "args": [
                    "-I",
                    "-m",
                    "trace_mechanism.mcp_server",
                    "--manifest",
                    str(manifest),
                ],
            }
        }
    }
    tool = "mcp__agent-trace__read_chat_context"
    prompt = (
        f"Call {tool} for provider codex, session_id {sid}, scope full_thread, "
        "include_children true and limit 1. Return its text_sha256 unchanged."
    )
    result = subprocess.run(
        [
            "claude",
            "-p",
            prompt,
            "--strict-mcp-config",
            "--mcp-config",
            json.dumps(config),
            "--tools",
            "",
            "--allowedTools",
            tool,
            "--setting-sources",
            "project",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--output-format",
            "stream-json",
            "--verbose",
        ],
        cwd=home,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    calls = [
        block
        for e in events
        if e.get("type") == "assistant"
        for block in e["message"]["content"]
        if block.get("type") == "tool_use"
    ]
    assert any(c["name"] == tool for c in calls), "No actual MCP read in host session"
    assert expected in events[-1].get("result", ""), (
        "Fresh agent retrieved different bytes"
    )


def run(args, home):
    folder = home / "custom-codex/sessions"
    folder.mkdir(parents=True)
    files = []
    for source in sorted((ROOT / "examples/launch-review").glob("*.jsonl")):
        path = folder / source.name
        shutil.copyfile(source, path)
        files.append(path)
    parent = folder / "coordinator.jsonl"
    sid = json.loads(parent.read_text().splitlines()[0])["payload"]["id"]
    title = 'Release replay <button id="record-injection">Run me</button>'
    (folder.parent / "session_index.jsonl").write_text(
        json.dumps({"id": sid, "thread_name": title})
    )
    env = dict(
        os.environ,
        HOME=str(home),
        CODEX_HOME=str(folder.parent),
        CLAUDE_CONFIG_DIR=str(home / "custom-claude"),
        AGENT_TRACE_PROMPTS=str(home / "prompts"),
    )
    python = os.path.abspath(args.python)
    server = subprocess.Popen(
        [python, "-I", "-m", "trace_mechanism.workbench.server", "--no-browser"],
        cwd=home,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
    )
    try:
        url = server.stdout.readline().strip()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.chrome)
            ctx = browser.new_context(
                viewport={"width": 1250, "height": 800},
                reduced_motion="reduce",
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(url)
            page.locator("#agent-trace-rows .title-text").filter(has_text=title).click()
            expect(page.locator("#mission-team-workers button")).to_have_count(2)
            page.get_by_text("Full thread detailed", exact=True).filter(
                visible=True
            ).first.click()
            page.locator("#preview-scope").click()
            expect(page.locator("#preview-sources li")).to_have_count(3)
            assert page.locator("#record-injection").count() == 0
            preview = page.locator("#preview-text").inner_text()
            for path in files:
                assert (
                    json.loads(path.read_text().splitlines()[0])["payload"]["id"]
                    in preview
                )
            append = {
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "thread_id": sid,
                    "turn_id": "after-preview",
                    "item": {
                        "id": "live-arrival",
                        "type": "CommandExecution",
                        "command": "echo arrived",
                        "aggregated_output": "arrival-after-preview",
                        "exit_code": 0,
                    },
                },
            }
            with parent.open("a") as stream:
                stream.write(json.dumps(append) + "\n")
            page.locator("#preview-copy").click()
            expect(page.locator("#trace-preview")).not_to_be_visible()
            assert page.evaluate("navigator.clipboard.readText()") == preview
            expect(
                page.locator('.activity-tile[data-event-id="live-arrival"]')
            ).to_be_visible(timeout=15000)
            page.locator("#mission-pane-copy-capsule").click()
            expect(page.locator("#mission-receipt")).to_contain_text("Copied")
            page.wait_for_function(
                "async () => (await navigator.clipboard.readText()).includes('arrival-after-preview')"
            )
            copied = page.evaluate("navigator.clipboard.readText()")
            page.locator("#manage-prompts").click()
            page.locator("#prompt-name").fill("personal")
            body = "# Check the run\nCompare the captured evidence."
            page.locator("#prompt-md").fill("---\ntitle: My own review\n---\n" + body)
            page.locator("#prompt-preview").click()
            expect(page.locator("#prompt-output")).to_have_text(body)
            page.locator("#prompt-save").click()
            page.reload()
            page.get_by_text("My own review", exact=True).first.click()
            page.wait_for_function(
                "async text => (await navigator.clipboard.readText()) === text",
                arg=body,
            )
            page.set_viewport_size({"width": 760, "height": 620})
            page.locator("#agent-trace-rows .title-text").filter(has_text=title).click()
            page.locator("#preview-scope").focus()
            page.keyboard.press("Enter")
            expect(page.locator("#trace-preview")).to_be_visible()
            if args.screenshot:
                page.screenshot(path=args.screenshot)
            page.keyboard.press("Escape")
            expect(page.locator("#trace-preview")).not_to_be_visible()
            assert not errors, errors
            browser.close()
        manifest = home / "selected.json"
        assert not manifest.exists()
        subprocess.run(
            [
                python,
                "-I",
                "-m",
                "trace_mechanism.setup",
                "register",
                *files,
                "--manifest",
                manifest,
            ],
            cwd=home,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        digest = hashlib.sha256(copied.encode()).hexdigest()
        if args.claude:
            fresh_agent(python, home, manifest, sid, digest)
        print(
            json.dumps(
                {
                    "sessions": len(files),
                    "clipboard_sha256": digest,
                    "fresh_agent_verified": args.claude,
                }
            )
        )
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Interpreter with the candidate and MCP extra installed",
    )
    parser.add_argument("--chrome", help="Optional Chromium executable")
    parser.add_argument("--screenshot")
    parser.add_argument(
        "--claude",
        action="store_true",
        help="Call a signed-in Claude Code model on public fixtures",
    )
    with tempfile.TemporaryDirectory(prefix="trace-journey-") as tmp:
        run(parser.parse_args(), Path(tmp))
