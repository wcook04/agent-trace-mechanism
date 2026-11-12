"""Cold-user journeys through the same local transport as the packaged window."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from trace_mechanism.workbench.server import start

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def app(native=False):
    server, _ = start()
    if native:
        server.desktop = {"copy": lambda text: text}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(path, body=None, headers=None):
        req = Request(
            server.origin + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={"X-Agent-Trace-Key": server.token, **(headers or {})},
        )
        with urlopen(req, timeout=10) as res:
            return json.load(res)

    try:
        yield request
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(tmp_path))
    for var in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "AGENT_TRACE_PROMPTS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("hosts", [(), ("codex",), ("claude",), ("codex", "claude")])
def test_cold_provider_matrix(isolated, hosts):
    for host in hosts:
        folder = isolated / (
            ".codex/sessions" if host == "codex" else ".claude/projects"
        )
        folder.mkdir(parents=True)
        fixture = (
            "examples/native-command.jsonl"
            if host == "codex"
            else "tests/fixtures/claude.jsonl"
        )
        shutil.copyfile(ROOT / fixture, folder / "chat.jsonl")
    with app() as api:
        rows = api("/mission-index")["index"]["active_rows"]
        assert {r["provider"] for r in rows} == {
            "claude_code" if h == "claude" else h for h in hosts
        }
        assert api("/prompt-shelf")["items"]
        for row in rows:
            identity = {"ref": row["ref"]}
            assert api("/activity", identity)["events"]
            detailed = api("/trace", {**identity, "depth": "full"})["text"]
            compact = api("/trace", {**identity, "depth": "summary"})["text"]
            assert detailed != compact
            evidence = "Ran 2 tests" if row["provider"] == "codex" else "old line"
            assert evidence in detailed and evidence not in compact
            assert api("/trace", {**identity, "turns": 1})["text"]
    assert not list(isolated.rglob("*.toml"))
    assert not list(isolated.rglob("*.md"))


def test_copy_older_codex_session_from_another_project(isolated):
    fixture = (ROOT / "examples/codex.jsonl").read_text()
    _, _, events = fixture.partition("\n")
    home = isolated / ".codex/sessions"
    other_project = isolated / "other-project"
    older = home / "2026/01/01"
    recent = home / "2026/02/01"
    older.mkdir(parents=True)
    recent.mkdir(parents=True)
    target_id = "019b76da-a800-7000-8000-000000000001"
    target = older / "older.jsonl"

    def record(path, session_id, cwd, answer, mtime):
        meta = {"type": "session_meta", "payload": {"id": session_id, "cwd": str(cwd)}}
        path.write_text(json.dumps(meta) + "\n" + events.replace("Update prepared.", answer))
        os.utime(path, (mtime, mtime))

    record(target, target_id, other_project, "Other project answer.", 1767225600)
    for i in range(81):
        record(recent / f"current-{i}.jsonl", f"current-{i}", isolated, "Current project answer.", 1769904000)

    with app(native=True) as api:
        rows = api("/mission-index")["index"]["active_rows"]
        assert len(rows) == 82 and rows[-1]["session_id"] == target_id
        identity = {"provider": "codex", "session_id": target_id}
        preview = api("/trace", {**identity, "depth": "summary", "preview": True})
        ref = rows[-1]["ref"]
        assert preview["sources"][0]["ref"] == ref
        assert preview["sessions"] == 1
        assert "Other project answer." in preview["text"]
        assert "Current project answer." not in preview["text"]
        copied = api("/copy-preview", {"preview_handle": preview["preview_handle"], "sha256": preview["text_sha256"]})
        assert copied["verb"] == preview["text"]

        record(target, target_id, other_project, "Updated other project answer.", 1767225601)
        refreshed = api("/trace", {"ref": ref, "depth": "summary", "deliver": "copy"})
        assert refreshed["sources"][0]["ref"] == ref
        assert "Updated other project answer." in refreshed["verb"]


@pytest.mark.parametrize("location", ["default", "environment", "tilde", "saved"])
def test_new_user_history_locations_and_restart(isolated, monkeypatch, capsys, location):
    launcher = isolated / "unrelated project"
    launcher.mkdir()
    monkeypatch.chdir(launcher)
    homes = {
        provider: isolated / (f".{provider}" if location == "default" else f"history storage é/{provider} home")
        for provider in ("codex", "claude")
    }
    if location in ("environment", "tilde"):
        for provider, variable in (("codex", "CODEX_HOME"), ("claude", "CLAUDE_CONFIG_DIR")):
            home = homes[provider]
            value = "~/" + home.relative_to(isolated).as_posix() if location == "tilde" else str(home)
            monkeypatch.setenv(variable, value)
    with app() as api:
        assert api("/mission-index")["index"]["active_rows"] == []

    sources = {}
    fixture = (ROOT / "examples/codex.jsonl").read_text(encoding="utf-8")
    for sid, folder, answer in (
        ("active-chat", "sessions/2026/01/01", "Active answer."),
        ("archived-chat", "archived_sessions", "Archived answer."),
    ):
        path = homes["codex"] / folder / f"{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fixture.replace("synthetic-codex", sid).replace("Update prepared.", answer), encoding="utf-8")
        sources[sid] = path
    native = homes["codex"] / "sessions/native.jsonl"
    shutil.copyfile(ROOT / "examples/native-command.jsonl", native)
    claude = homes["claude"] / "projects/another-project/chat.jsonl"
    claude.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/fixtures/claude.jsonl", claude)
    (homes["codex"] / "session_index.jsonl").write_text(
        json.dumps({"id": "active-chat", "thread_name": "My named conversation"}) + "\n", encoding="utf-8")
    (native.parent / "partial.jsonl").write_text('{"type":', encoding="utf-8")
    if location != "saved":
        from trace_mechanism.setup import main
        for provider, expected in (("codex", set(sources)), ("claude", {"synthetic-claude"})):
            monkeypatch.setattr(sys, "argv", ["setup", "list", "--provider", provider])
            main()
            listed = json.loads(capsys.readouterr().out)
            assert expected <= {row.get("session_id") for row in listed}
    if location == "saved":
        with app() as api:
            api("/history-folders", {provider: str(home) for provider, home in homes.items()})
        # Persisted choices must survive a restart and take precedence over
        # launcher defaults, including defaults that contain no histories.
        monkeypatch.setenv("CODEX_HOME", str(isolated / "unused codex home"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(isolated / "unused claude home"))

    for _ in range(2):
        with app(native=True) as api:
            index = api("/mission-index")["index"]
            rows = index["active_rows"]
            assert len(rows) == 4
            for provider, home in homes.items():
                assert all(Path(root).parent == home for root in index["discovery"][provider]["roots"])
            for row in rows:
                capture = api("/trace", {"ref": row["ref"], "depth": "full", "preview": True})
                assert capture["sources"][0]["ref"] == row["ref"]
                assert capture["text"]
                copied = api("/copy-preview", {"preview_handle": capture["preview_handle"], "sha256": capture["text_sha256"]})
                assert copied["verb"] == capture["text"]
                if row["session_id"] == "active-chat":
                    assert "Active answer." in capture["text"] and not row["provider_archived"]
                    assert row["source_title"] == "My named conversation"
                elif row["session_id"] == "archived-chat":
                    assert "Archived answer." in capture["text"] and row["provider_archived"]
                elif row["provider"] == "claude_code":
                    assert "Update complete." in capture["text"]
                else:
                    assert "Ran 2 tests" in capture["text"]

    # Copy the preview actually reviewed, even after the source advances;
    # refreshing must select the same recording and return its new contents.
    with app(native=True) as api:
        identity = {"provider": "codex", "session_id": "active-chat", "depth": "summary"}
        before = api("/trace", {**identity, "preview": True})
        path = sources["active-chat"]
        path.write_text(path.read_text(encoding="utf-8").replace("Active answer.", "New answer."), encoding="utf-8")
        frozen = api("/copy-preview", {"preview_handle": before["preview_handle"], "sha256": before["text_sha256"]})
        assert frozen["verb"] == before["text"]
        after = api("/trace", {**identity, "deliver": "copy"})
        assert "New answer." in after["verb"] and after["text_sha256"] != before["text_sha256"]
        assert after["sources"][0]["ref"] == before["sources"][0]["ref"]


def test_installed_console_launch_from_unrelated_directory(isolated):
    launcher = isolated / "launch from here"
    launcher.mkdir()
    command = Path(sysconfig.get_path("scripts")) / ("agent-trace-app.exe" if os.name == "nt" else "agent-trace-app")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    # Keep startup bounded without sleeping or leaving a server behind on failure.
    with subprocess.Popen([str(command), "--no-browser"], cwd=launcher, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8") as process:
        with ThreadPoolExecutor(max_workers=1) as reader:
            try:
                url = reader.submit(process.stdout.readline).result(timeout=20).strip()
                origin, token = url.split("/#k=", 1)
                with urlopen(origin, timeout=10) as response:
                    assert b"Missions" in response.read()
                request = Request(origin + "/mission-index", headers={"X-Agent-Trace-Key": token})
                with urlopen(request, timeout=10) as response:
                    assert json.load(response)["index"]["active_rows"] == []
                folder = isolated / ".codex/archived_sessions"
                folder.mkdir(parents=True)
                shutil.copyfile(ROOT / "examples/codex.jsonl", folder / "saved-chat.jsonl")
                with urlopen(request, timeout=10) as response:
                    (row,) = json.load(response)["index"]["active_rows"]
                assert row["provider_archived"]
                capture_request = Request(
                    origin + "/trace",
                    data=json.dumps({"provider": "codex", "session_id": row["session_id"], "depth": "summary"}).encode(),
                    headers={"X-Agent-Trace-Key": token},
                )
                with urlopen(capture_request, timeout=10) as response:
                    capture = json.load(response)
                assert "Update prepared." in capture["text"]
                assert capture["sources"][0]["ref"] == row["ref"]
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def test_parent_and_workers_keep_their_own_evidence(isolated):
    d = isolated / ".codex/sessions"
    d.mkdir(parents=True)
    for path in (ROOT / "examples/launch-review").glob("*.jsonl"):
        shutil.copyfile(path, d / path.name)
    with app() as api:
        rows = api("/mission-index")["index"]["active_rows"]
        parent = next(r for r in rows if not r["thread_parent"])
        identity = {"ref": parent["ref"]}
        assert len(api("/activity", identity)["team"]["workers"]) == 2
        full = api("/trace", {**identity, "depth": "full"})
        assert full["sessions"] == 3 and all(
            r["session_id"] in full["text"] for r in rows
        )
        assert api("/trace", {**identity, "turns": 1})["sessions"] == 1
        assert api("/trace", {**identity, "closeout": True})["text"]


def test_app_key_file_boundary_and_prompt_restart(isolated):
    with app() as api:
        for bad in [
            {"X-Agent-Trace-Key": "wrong"},
            {"Host": "foreign.invalid"},
            {"Origin": "https://foreign.invalid"},
        ]:
            with pytest.raises(HTTPError) as err:
                api("/prompt-shelf", headers=bad)
            assert err.value.code in (401, 403)
        initial = api("/prompt-shelf/continue")
        update = {
            "slug": "continue",
            "raw": "# Local only\nCheck this.",
            "revision": initial["revision"],
        }
        assert api("/save-prompt", update)["user"]
        for invalid in [update, {"slug": "../outside", "raw": "example"}]:
            with pytest.raises(HTTPError):
                api("/save-prompt", invalid)
        with pytest.raises(HTTPError):
            api("/trace", {"ref": str(ROOT / "examples/native-command.jsonl")})
    with app() as api:
        assert api("/prompt-shelf/continue")["body"] == update["raw"]
        (isolated / ".agent-trace/prompts/continue.md").unlink()
        assert api("/prompt-shelf/continue")["raw"] == initial["raw"]


def test_mixed_turn_scope_and_mcp_agree(isolated):
    from trace_mechanism.agent_tools import AgentTools

    folder = isolated / ".codex/sessions"
    folder.mkdir(parents=True)
    path = folder / "mixed.jsonl"
    lines = (ROOT / "examples/native-command.jsonl").read_text().splitlines()
    sid = json.loads(lines[0])["payload"]["id"]
    legacy = [
        json.dumps({"type": "event_msg", "payload": payload})
        for payload in (
            {"type": "task_started", "turn_id": "old"},
            {"type": "user_message", "message": "Earlier compatibility prompt"},
            {"type": "task_complete", "last_agent_message": "Earlier closeout"},
        )
    ]
    path.write_text("\n".join([lines[0], *legacy, *lines[1:]]) + "\n")
    host = AgentTools([dict(provider="codex", session_id=sid, path=path)])
    with app() as api:
        (row,) = api("/mission-index")["index"]["active_rows"]
        full = api("/trace", {"ref": row["ref"], "depth": "full"})
        retrieved = host.read_chat_context("codex", sid, scope="full_thread")
        assert full["text_sha256"] == retrieved["text_sha256"]
        assert (
            "Earlier compatibility prompt" in full["text"]
            and "Ran 2 tests" in full["text"]
        )
        recent = api("/trace", {"ref": row["ref"], "turns": 1})
        assert "Earlier compatibility prompt" not in recent["text"]
        assert "Ran 2 tests" in recent["text"]
        with path.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {"type": "task_started", "turn_id": "next"},
                    }
                )
                + "\n"
            )
            stream.write('{"pending":')
        (refreshed,) = api("/mission-index")["index"]["active_rows"]
        assert (
            refreshed["active_turn"]["turn_index"]
            > refreshed["latest_completed_turn"]["turn_index"]
        )
        assert api("/trace", {"ref": row["ref"]})["warnings"]


def test_claude_identity_closeout_and_partial_lines(isolated):
    folder = isolated / ".claude/projects/project"
    folder.mkdir(parents=True)
    path = folder / "source.jsonl"
    records = [
        {
            "type": "user",
            "sessionId": "first",
            "message": {"content": [{"type": "text", "text": "Hello"}]},
        },
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Still working"}]},
        },
    ]
    path.write_text("\n".join(map(json.dumps, records)) + '\n{"incomplete"')
    with app() as api:
        (row,) = api("/mission-index")["index"]["active_rows"]
        assert row["worker_state"] == "working"
        assert api("/trace", {"ref": row["ref"]})["warnings"]
        with pytest.raises(HTTPError):
            api("/trace", {"ref": row["ref"], "closeout": True})
        with path.open("a") as stream:
            stream.write(
                '\n{"type":"user","sessionId":"second","message":{"content":"alien"}}\n'
            )
        with pytest.raises(HTTPError):
            api("/trace", {"ref": row["ref"]})


def test_ambiguous_children_and_untrusted_writes(isolated):
    folder = isolated / ".codex/sessions"
    folder.mkdir(parents=True)
    for path in (ROOT / "examples/launch-review").glob("*.jsonl"):
        shutil.copyfile(path, folder / path.name)
    shutil.copyfile(folder / "access-review.jsonl", folder / "duplicate.jsonl")
    with app() as api:
        index = api("/mission-index")["index"]
        assert index["ambiguous_sessions"] == 1
        assert len(index["active_rows"]) == 4
        parent = next(
            row
            for row in index["active_rows"]
            if row["source_file"] == "coordinator.jsonl"
        )
        with pytest.raises(HTTPError):
            api("/trace", {"ref": parent["ref"]})
        for headers in (
            {"Origin": "null"},
            {"X-Agent-Trace-Key": ""},
            {"Host": "malicious.example"},
        ):
            with pytest.raises(HTTPError):
                api("/save-prompt", {"slug": "intrusion", "raw": "test"}, headers)


def test_symlink_writes_and_replaced_history(isolated):
    outside = isolated / "private.md"
    outside.write_text("secret")
    prompts = isolated / ".agent-trace/prompts"
    prompts.mkdir(parents=True)
    try:
        (prompts / "linked.md").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows has not granted this user symbolic-link creation.")
        raise
    folder = isolated / ".codex/sessions"
    folder.mkdir(parents=True)
    shutil.copyfile(ROOT / "examples/native-command.jsonl", folder / "coordinator.jsonl")
    with app() as api:
        (parent,) = api("/mission-index")["index"]["active_rows"]
        for url, body in (
            ("/prompt-shelf/linked", None),
            ("/save-prompt", {"slug": "linked", "raw": "overwritten"}),
            ("/prompt-shelf/%2e%2e%2fprivate", None),
            ("/window", {"action": "save", "value": "text"}),
        ):
            with pytest.raises(HTTPError):
                api(url, body)
        assert outside.read_text() == "secret"
        (folder / "coordinator.jsonl").unlink()
        (folder / "coordinator.jsonl").symlink_to(outside)
        with pytest.raises(HTTPError):
            api("/activity", {"ref": parent["ref"]})


def test_large_tool_output_preserves_exact_terminal_message(isolated):
    from trace_mechanism.workbench.library import Library

    folder = isolated / ".claude/projects/large"
    folder.mkdir(parents=True)
    path = folder / "session.jsonl"
    rows = [
        {"sessionId": "large", "type": "user", "message": {"content": "First prompt"}},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Checking the output"}]},
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "large-tool",
                        "content": "x" * 2_000_000,
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "Recorded final answer."}],
                "stop_reason": "end_turn",
            },
        },
        {"type": "user", "message": {"content": "A new open turn"}},
    ]
    path.write_text("\n".join(map(json.dumps, rows)) + "\n")
    lib = Library()
    (row,) = lib.discover()
    assert row["history_before"] > 0 and row["worker_state"] == "working"
    identity = {"ref": row["ref"]}
    assert lib.trace({**identity, "closeout": True})["text"] == "Recorded final answer."
    with pytest.raises(ValueError):
        lib.trace({**identity, "turns": 1, "closeout": True})
    assert "First prompt" not in lib.trace({**identity, "turns": 1})["text"]


@pytest.mark.parametrize("damaged", [b'{"bad":', b"[]", b'{"codex:a":4}', b"\xff"])
def test_damaged_preferences_preserved_without_hiding_sessions(isolated, damaged):
    folder = isolated / ".codex/sessions"
    folder.mkdir(parents=True)
    shutil.copyfile(ROOT / "examples/codex.jsonl", folder / "source.jsonl")
    marker = isolated / ".agent-trace/mission-markers.json"
    marker.parent.mkdir()
    marker.write_bytes(damaged)
    with app() as api:
        index = api("/mission-index")["index"]
        assert len(index["active_rows"]) == 1 and index["operator_markers"] == {}
        (backup,) = marker.parent.glob("mission-markers.damaged-*.json")
        assert backup.read_bytes() == damaged and str(backup) in index["marker_notice"]
        api("/marker", {"mission_key": "codex:a", "pinned": True})
        refreshed = api("/mission-index")["index"]
        assert (
            refreshed["operator_markers"]["codex:a"]["pinned"]
            and not refreshed["marker_notice"]
        )
        assert backup.read_bytes() == damaged


def test_choose_nested_workers_or_parent_from_oversize_tree(isolated):
    from trace_mechanism.workbench.library import Library

    folder = isolated / ".codex/sessions"
    folder.mkdir(parents=True)
    fixture = (ROOT / "examples/codex.jsonl").read_text().splitlines()
    for i in range(67):
        parent = None if not i else "worker1" if i == 2 else "worker0"
        meta = {"id": f"worker{i}", "agent_nickname": f"Name {i}"}
        if parent:
            meta["parent_thread_id"] = parent
        (folder / f"{i}.jsonl").write_text(
            "\n".join(
                [json.dumps({"type": "session_meta", "payload": meta}), *fixture[1:]]
            )
            + "\n"
        )
    lib = Library()
    rows = {r["session_id"]: r for r in lib.discover()}
    key = {"ref": rows["worker0"]["ref"]}
    assert rows["worker1"]["agent_name"] == "Name 1"
    assert len(lib.capture_options(key)["sources"]) == 67
    with pytest.raises(ValueError, match="64"):
        lib.trace(key)
    selected = [rows[sid]["ref"] for sid in ("worker1", "worker2")]
    trace = lib.trace({**key, "selected_refs": selected})
    assert {s["session_id"] for s in trace["sources"]} == {"worker1", "worker2"}
    assert trace["discovered"] == 67 and "65 related" in trace["warnings"][0]
    (folder / "2.jsonl").unlink()
    lib.discover()
    assert "worker2" in lib.capture_options(key)["unavailable"]
    assert lib.trace({**key, "selected_refs": [key["ref"]]})["sessions"] == 1
    with pytest.raises(ValueError):
        lib.trace({**key, "selected_refs": selected})
    tail = lib.trace({**key, "activity_only": True})
    assert tail["sessions"] == 1 and "Source bytes" in tail["text"]


def test_prompt_removal_respects_starter_and_revision(isolated):
    with app() as api:
        starter = api("/prompt-shelf/continue")
        override = api(
            "/save-prompt",
            {"slug": "continue", "revision": starter["revision"], "raw": "Personal"},
        )
        with pytest.raises(HTTPError):
            api("/remove-prompt", {"slug": "continue", "revision": starter["revision"]})
        assert api(
            "/remove-prompt", {"slug": "continue", "revision": override["revision"]}
        )["restored"]
        assert api("/prompt-shelf/continue")["raw"] == starter["raw"]
        custom = api("/save-prompt", {"slug": "mine", "raw": "Custom"})
        assert not api(
            "/remove-prompt", {"slug": "mine", "revision": custom["revision"]}
        )["restored"]
        with pytest.raises(HTTPError):
            api("/prompt-shelf/mine")


def test_archive_move_duplicate_and_exact_file_capture(isolated):
    from trace_mechanism.workbench.library import Library

    active = isolated / ".codex/sessions/a.jsonl"
    archived = isolated / ".codex/archived_sessions/a.jsonl"
    archived.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "examples/codex.jsonl", archived)
    lib = Library()
    (first,) = lib.discover()
    assert first["provider_archived"]
    original = lib.trace({"ref": first["ref"]})
    active.parent.mkdir()
    archived.rename(active)
    (moved,) = lib.discover()
    assert moved["ref"] == first["ref"]
    assert moved["session_id"] == first["session_id"] and not moved["provider_archived"]
    assert lib.trace({"ref": moved["ref"]})["text_sha256"] == original["text_sha256"]
    archived.write_text(
        active.read_text().replace("Update prepared.", "Archived answer.")
    )
    rows = lib.discover()
    assert len(rows) == 2 and all(r["ambiguous"] for r in rows)
    with pytest.raises(ValueError, match="ambiguous"):
        lib.select({"provider": "codex", "session_id": first["session_id"]})
    for row in rows:
        capture = lib.trace({"ref": row["ref"], "closeout": True})
        assert capture["text"] == (
            "Archived answer." if row["provider_archived"] else "Update prepared."
        )
        assert capture["sources"][0]["ref"] == row["ref"]


def test_nested_claude_workers_and_unresolved_links(isolated):
    from trace_mechanism.workbench.library import Library

    fixture = (ROOT / "tests/fixtures/claude.jsonl").read_text()
    sid = json.loads(fixture.splitlines()[0])["sessionId"]
    project = isolated / ".claude/projects/demo"
    workers = project / sid / "subagents"
    (workers / "nested").mkdir(parents=True)
    (project / (sid + ".jsonl")).write_text(fixture)
    for folder in (workers, workers / "nested"):
        (folder / "agent-worker.jsonl").write_text(fixture)
    lib = Library()
    rows = lib.discover()
    parent = next(r for r in rows if r["session_id"] == sid)
    key = {"ref": parent["ref"]}
    assert len(lib.activity(key)["team"]["workers"]) == 2
    assert len({r["ref"] for r in rows}) == 3
    full = lib.trace(key)
    assert full["sessions"] == 3 and full["coverage"]["relationships"] == "discovered"
    dangling = project / "different-session/subagents/unknown.jsonl"
    dangling.parent.mkdir(parents=True)
    dangling.write_text(fixture)
    rows = lib.discover()
    assert len(rows) == 4
    assert next(r for r in rows if r["source_file"].endswith("unknown.jsonl"))[
        "unlinked"
    ]
    selected = lib.trace({**key, "selected_refs": [key["ref"]]})
    assert selected["discovery_health"]["claude"]["unlinked"] == 1
    assert selected["coverage"] == dict(
        scope="explicit", selected=1, discovered=3, excluded=2, relationships="discovered"
    )


def test_bounded_turn_evidence_with_and_without_a_boundary(isolated):
    from trace_mechanism.workbench.library import Library

    path = isolated / ".codex/sessions/large.jsonl"
    path.parent.mkdir(parents=True)
    fixture = (ROOT / "examples/codex.jsonl").read_text()
    path.write_text(fixture + json.dumps({"padding": "x" * 200000}) + "\n")
    lib = Library()
    (row,) = lib.discover()
    assert row["turn_observation"] == "bounded" and "preferred_trace_turn" not in row
    with path.open("a") as stream:
        stream.write(fixture.split("\n", 1)[1].replace("turn-1", "turn-last"))
    (row,) = lib.discover()
    observed = row["preferred_trace_turn"]
    assert observed["turn_id"] == "turn-last" and observed["turn_index"] is None
    assert row["worker_state"] == "finished"


def test_worker_append_while_parent_is_being_captured(isolated, monkeypatch):
    from trace_mechanism.workbench import library

    folder = isolated / ".codex/sessions"
    folder.mkdir(parents=True)
    for source in (ROOT / "examples/launch-review").glob("*.jsonl"):
        shutil.copyfile(source, folder / source.name)
    lib = library.Library()
    parent = next(r for r in lib.discover() if not r["thread_parent"])
    load = library.codex_native.load_rollout

    def append_after_parent(path, **kwargs):
        result = load(path, **kwargs)
        if path.name == "coordinator.jsonl":
            with (folder / "access-review.jsonl").open("a") as worker:
                worker.write("{}\n")
        return result

    monkeypatch.setattr(library.codex_native, "load_rollout", append_after_parent)
    with pytest.raises(ValueError, match="changed during capture"):
        lib.trace({"ref": parent["ref"]})


def test_exact_mcp_selection_of_claude_worker_and_disconnected_codex(isolated):
    from trace_mechanism.agent_tools import AgentTools
    from trace_mechanism.mcp_server import load_manifest
    from trace_mechanism.setup import register
    from trace_mechanism.workbench.library import Library

    project = isolated / '.claude/projects/example'
    sid = 'synthetic-claude'
    parent = project / (sid + '.jsonl')
    worker = project / sid / 'subagents/nested/agent-chosen.jsonl'
    sibling = worker.with_name('agent-private.jsonl')
    worker.parent.mkdir(parents=True)
    fixture = (ROOT / 'tests/fixtures/claude.jsonl').read_text()
    for path, label in ((parent, 'Coordinator'), (worker, 'Test worker'), (sibling, 'Private sibling')):
        path.write_text(fixture.replace('Update complete.', label))
    codex = isolated / '.codex/archived_sessions/other.jsonl'
    codex.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / 'examples/codex.jsonl', codex)
    (codex.parent / 'unidentified.jsonl').write_text('{}\n')
    lib = Library()
    by_path = {Path(r['source_file']).name: r for r in lib.discover()}
    refs = [by_path[p.name]['ref'] for p in (parent, worker, codex)]
    manifest = isolated / 'selected.json'
    register([parent, worker, codex], manifest)
    api = AgentTools(load_manifest(manifest))
    for chosen in (refs[:2], refs):
        actual = api.read_selected_context(chosen)
        preview = lib.trace({'ref': refs[0], 'selected_refs': chosen})
        assert actual['text_sha256'] == preview['text_sha256']
        assert 'Coordinator' in actual['text'] and 'Test worker' in actual['text'] and 'Private sibling' not in actual['text']
        assert preview['discovery_health']['codex']['unsupported'] == 1
        assert preview['coverage']['relationships'] == 'discovered'
    with pytest.raises(ValueError, match='unregistered'):
        api.read_selected_context([by_path[sibling.name]['ref']])
    with pytest.raises(ValueError, match='recording IDs'):
        api.read_chat_context('claude', sid, include_children=True)


def test_overlapping_native_previews_and_folder_persistence(isolated):
    src = isolated / 'custom/sessions'
    src.mkdir(parents=True)
    shutil.copyfile(ROOT / 'examples/codex.jsonl', src / 'a.jsonl')
    text = (src / 'a.jsonl').read_text().replace('synthetic-codex', 'second').replace('Update prepared.', 'Second answer.')
    (src / 'b.jsonl').write_text(text)
    with app() as api:
        api('/history-folders', {'codex': str(src.parent)})
    with app(native=True) as api:
        rows = api('/mission-index')['index']['active_rows']
        captures = [api('/trace', {'ref': r['ref'], 'preview': True, 'closeout': True}) for r in rows]
        assert len(captures) == 2
        for capture in captures:
            out = api('/copy-preview', {'sha256': capture['text_sha256'], 'preview_handle': capture['preview_handle']})
            assert out['verb'] == capture['text']


def test_snapshot_retention_expires_old_handles():
    from trace_mechanism.agent_tools import SnapshotStore

    store = SnapshotStore(max_count=2, max_bytes=100)
    for key in ('a', 'b', 'c'):
        store[key] = key
    assert store.get('a') is None and store['b'] == 'b'
    store['b'] = 'different content'
    assert store['b'] == 'b'
    with pytest.raises(ValueError, match='budget'):
        store['large'] = 'x' * 100
