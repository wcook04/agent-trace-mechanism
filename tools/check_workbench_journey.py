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


def fresh_agent(python, home, manifest, provider, sid, expected):
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
        f"Call {tool} for provider {provider}, session_id {sid}, scope full_thread, "
        f"include_children {str(provider == 'codex').lower()} and limit 1. Return its text_sha256 unchanged."
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


def fresh_codex(python, home, manifest, provider, sid, expected):
    args = ["-I", "-m", "trace_mechanism.mcp_server", "--manifest", str(manifest)]
    answer = home / f"model-answer-{provider}.txt"
    prompt = (
        f"Call release_read.read_chat_context for provider {provider}, session_id {sid}, "
        f"scope full_thread, include_children {str(provider == 'codex').lower()} and limit 1. Return its text_sha256 alone. "
        "Use no shell or filesystem tools."
    )
    result = subprocess.run(
        [
            "codex",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "-c",
            "mcp_servers.release_read.command=" + json.dumps(python),
            "-c",
            "mcp_servers.release_read.args=" + json.dumps(args),
            "-c",
            'mcp_servers.release_read.tools.read_chat_context.approval_mode="approve"',
            "-o",
            answer,
            prompt,
        ],
        cwd=home,
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert any(
        item.get("type") == "mcp_tool_call"
        and item.get("server") == "release_read"
        and item.get("tool") == "read_chat_context"
        and item.get("status") == "completed"
        for event in events
        if isinstance(item := event.get("item"), dict)
    ), "Codex did not complete the read"
    assert expected in answer.read_text(), "Codex returned a different digest"


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
    claude_path = home / "custom-claude/projects/example/claude.jsonl"
    claude_path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/fixtures/claude.jsonl", claude_path)
    claude_sid = json.loads(claude_path.read_text().splitlines()[0])["sessionId"]
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
            workers = page.locator("#mission-team-workers button")
            expect(workers).to_have_count(2)
            workers.first.click()
            page.locator("#mission-team-open").click()
            expect(page.locator("#mission-team-workers button")).to_have_count(0)
            page.locator("#agent-trace-rows .title-text").filter(has_text=title).click()
            expect(workers).to_have_count(2)
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
            page.locator("#choose-sources").click()
            expect(page.locator("#source-options input:checked")).to_have_count(1)
            page.locator("#source-preview").click()
            expect(page.locator("#preview-sources li")).to_have_count(1)
            assert (
                "excluded by selection"
                in page.locator("#preview-scope-name").inner_text()
            )
            page.locator("#preview-close").click()
            page.locator("#agent-trace-rows .title-text").filter(
                has_text="Read and update example.txt."
            ).click()
            page.get_by_text("Full thread detailed", exact=True).filter(
                visible=True
            ).first.click()
            page.locator("#preview-scope").click()
            expect(page.locator("#preview-text")).to_contain_text("Update complete.")
            page.locator("#preview-copy").click()
            page.wait_for_function(
                "async () => (await navigator.clipboard.readText()).includes('Update complete.')"
            )
            claude_copy = page.evaluate("navigator.clipboard.readText()")
            page.locator("#manage-prompts").click()
            page.locator("#prompt-name").fill("personal")
            body = "# Check the run\nCompare the captured evidence."
            page.locator("#prompt-md").fill("---\ntitle: My own review\n---\n" + body)
            page.locator("#prompt-preview").click()
            expect(page.locator("#prompt-output")).to_have_text(body)
            page.keyboard.press("Escape")
            expect(page.locator("#editor-confirm")).to_be_visible()
            page.locator("#editor-keep").click()
            expect(page.locator("#prompt-md")).to_have_value(
                "---\ntitle: My own review\n---\n" + body
            )
            page.locator("#prompt-save").click()
            page.reload()
            page.get_by_text("My own review", exact=True).first.click()
            page.wait_for_function(
                "async text => (await navigator.clipboard.readText()) === text",
                arg=body,
            )
            # Two physical files claim one recorded ID. Pick each by location,
            # including the archive through its filter, and compare the actual preview.
            fixture = (ROOT / "examples/codex.jsonl").read_text()
            archive = folder.parent / "archived_sessions"
            archive.mkdir()
            title_index = folder.parent / "session_index.jsonl"
            with title_index.open("a") as index:
                index.write(
                    "\n"
                    + json.dumps(
                        {"id": "synthetic-codex", "thread_name": "Old incident notes"}
                    )
                )
            for target, answer in (
                (archive, "Archived answer"),
                (folder, "Active answer"),
            ):
                lines = fixture.replace("Update prepared.", answer).splitlines()
                lines.insert(1, json.dumps({"padding": "x" * 200000}))
                (target / "incident.jsonl").write_text("\n".join(lines) + "\n")
            page.reload()
            for archived, answer in (
                (True, "Archived answer"),
                (False, "Active answer"),
            ):
                page.locator(
                    '[data-mission-filter="archived" i]'
                    if archived
                    else '[data-mission-filter="all"]'
                ).click()
                candidates = page.locator("#agent-trace-rows .dropdown-row").filter(
                    has_text="Old incident notes"
                )
                candidate = (
                    candidates.filter(has_text="Archived in Codex")
                    if archived
                    else candidates.filter(has_not_text="Archived in Codex")
                )
                candidate.click()
                expect(candidate.locator(".col-fresh")).to_have_text("FINISHED")
                expect(page.locator("#agent-trace-detail-meta")).to_contain_text(
                    "turn-1"
                )
                page.locator("#preview-scope").click()
                expect(page.locator("#preview-text")).to_contain_text(answer)
                page.keyboard.press("Escape")
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
                claude_path,
                "--manifest",
                manifest,
            ],
            cwd=home,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        captures = {"codex": (sid, copied), "claude": (claude_sid, claude_copy)}
        checked = []
        for host, enabled, call in (
            ("Claude Code", args.claude, fresh_agent),
            ("Codex", args.codex, fresh_codex),
        ):
            if enabled:
                for provider, (identity, content) in captures.items():
                    digest = hashlib.sha256(content.encode()).hexdigest()
                    call(python, home, manifest, provider, identity, digest)
                    checked.append(
                        {"host": host, "source": provider, "clipboard_sha256": digest}
                    )
        print(
            json.dumps(
                {
                    "codex_sessions": len(files),
                    "claude_sessions": 1,
                    "verified_reads": checked,
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
    parser.add_argument(
        "--codex",
        action="store_true",
        help="Call a signed-in Codex model on public fixtures",
    )
    with tempfile.TemporaryDirectory(prefix="trace-journey-") as tmp:
        run(parser.parse_args(), Path(tmp))
