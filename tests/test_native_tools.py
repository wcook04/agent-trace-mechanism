"""Native retrieval contracts. Generated rows here are unit-test fixtures."""
import json
from pathlib import Path
import pytest
from trace_mechanism.agent_tools import AgentTools
from trace_mechanism.mcp_server import load_manifest


def records(path, session, items, parent=None):
    meta = {"id": session}
    if parent:
        meta["source"] = {"subagent": {"thread_spawn": {"parent_thread_id": parent}}}
    rows = [{"type": "session_meta", "payload": meta}]
    rows += [{"type": "event_msg", "payload": {"type": "item_completed", "thread_id": session,
              "turn_id": "turn-1", "item": item}} for item in items]
    path.write_text("".join(json.dumps(r)+"\n" for r in rows))


def command(ident, output="test failed", code=1):
    return {"type": "CommandExecution", "id": ident, "command": ["pytest"],
            "status": "completed", "exit_code": code, "aggregated_output": output}


def setup(tmp_path):
    root, child = tmp_path/"root.jsonl", tmp_path/"child.jsonl"
    records(root, "root", [command("a"), command("b", "passed", 0)])
    records(child, "child", [command("c"), command("d")], "root")
    manifest = tmp_path/"manifest.json"
    manifest.write_text(json.dumps([
        {"provider": "codex", "session_id": "root", "title": "Root", "path": root.name},
        {"provider": "codex", "session_id": "child", "title": "Child", "path": child.name,
         "parent_session_id": "root"}]))
    return AgentTools(load_manifest(manifest)), root, child, manifest


def test_cross_session_paging_exact_reads_and_incremental_changes(tmp_path):
    api, root, child, _ = setup(tmp_path)
    first = api.search_trace_items("codex", "root", failures_only=True, include_children=True, limit=2)
    assert [(x["session_id"], x["item_id"]) for x in first["items"]] == [("root", "a"), ("child", "c")]
    assert first["total_matches"] == 3 and first["next_offset"] == 2
    digest = first["snapshot_sha256"]
    second = api.search_trace_items("codex", "root", failures_only=True, snapshot_sha256=digest,
                                   limit=2, offset=2)
    assert [x["item_id"] for x in second["items"]] == ["d"]
    old = api.read_trace_item("codex", "child", "c", digest)
    assert old["payload"]["item"]["exit_code"] == 1
    records(child, "child", [command("c", "fixed", 0), command("d"), command("e", "new")], "root")
    change = api.read_trace_changes("codex", "root", digest, include_children=True)
    assert len(change["changes"]) == 1
    assert [x["item_id"] for x in change["changes"][0]["updated"]] == ["c"]
    assert [x["item_id"] for x in change["changes"][0]["added"]] == ["e"]
    assert api.read_trace_item("codex", "child", "c", digest) == old
    with pytest.raises(ValueError): api.read_trace_changes("codex", "root", digest)
    with pytest.raises(ValueError): api.search_trace_items("codex", "child", snapshot_sha256=digest)
    page = api.read_trace_item("codex", "child", "c", digest, limit=13)
    assert "payload" not in page and len(page["payload_json"]) == 13


def test_compact_and_exact_native_identity(tmp_path):
    api, root, child, manifest = setup(tmp_path)
    compact = api.read_chat_context("codex", "root")
    detailed = api.read_chat_context("codex", "root", "full_thread")
    assert "test failed" not in compact["text"] and "test failed" in detailed["text"]
    assert "CommandExecution" in compact["text"]
    records(root, "wrong-session", [command("x")])
    with pytest.raises(ValueError): api.read_chat_context("codex", "root")
    records(child, "child", [command("c")], "wrong-parent")
    with pytest.raises(ValueError): load_manifest(manifest)


@pytest.mark.parametrize("kwargs", [{"limit": True}, {"limit": 101}, {"offset": -1}, {"include_children": "yes"}])
def test_invalid_native_query_bounds(tmp_path, kwargs):
    api, *_ = setup(tmp_path)
    with pytest.raises(ValueError): api.search_trace_items("codex", "root", **kwargs)


def test_detail_field_handle_survives_source_changes(tmp_path):
    api, root, *_ = setup(tmp_path)
    original = "original output\n" * 1000 + "real failure tail"
    records(root, "root", [command("large", original)])
    detail = api.read_chat_context("codex", "root", "full_thread")
    row = json.loads(next(line.removeprefix("Native item: ") for line in detail["text"].splitlines()
                          if line.startswith("Native item: ")))
    ref = row["aggregated_output"]["evidence_ref"]
    records(root, "root", [command("large", "replacement", 0)])
    exact = api.read_trace_item("codex", ref["session_id"], ref["item_id"], ref["snapshot_sha256"],
                                field=ref["field"], limit=48000)
    assert exact["payload"] == original
    assert "payload_json" not in exact


def test_copied_native_core_matches_provenance():
    import hashlib
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root / "docs/provenance.json").read_text())["native_core"]
    assert hashlib.sha256((root / record["copy"]).read_bytes()).hexdigest() == record["sha256"]
