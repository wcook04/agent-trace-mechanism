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
