"""Cold-user journeys through the same local transport as the packaged window."""

from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from trace_mechanism.workbench.server import start

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def app():
    server, _ = start()
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
        parent = next(row for row in index["active_rows"] if not row["thread_parent"])
        with pytest.raises(HTTPError):
            api("/trace", {"ref": parent["ref"]})
        for headers in (
            {"Origin": "null"},
            {"X-Agent-Trace-Key": ""},
            {"Host": "malicious.example"},
        ):
            with pytest.raises(HTTPError):
                api("/save-prompt", {"slug": "intrusion", "raw": "test"}, headers)
        outside = isolated / "private.md"
        outside.write_text("secret")
        prompts = isolated / ".agent-trace/prompts"
        prompts.mkdir(parents=True)
        (prompts / "linked.md").symlink_to(outside)
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
        assert api("/mission-index")["index"]["operator_markers"]["codex:a"]["pinned"]
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
    assert trace["discovered"] == 67 and "65 discovered" in trace["warnings"][0]
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
