"""Optional maintainer differential replay against the original Structurer checkout."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from trace_mechanism import codex_native
from trace_mechanism.workbench.library import records, summary

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path, help="Original ai_workflow checkout")
    args = parser.parse_args()
    sys.path.insert(0, str(args.reference.resolve()))
    from tools.agent_trace_structurer import mcp_server as original

    with tempfile.TemporaryDirectory() as folder:
        original.SUPPORT = Path(folder)
        reader = original.build_activity_reader()
        for provider, file in (
            ("codex", "examples/codex.jsonl"),
            ("claude_code", "tests/fixtures/claude.jsonl"),
        ):
            path = ROOT / file
            original_sample = json.loads(
                subprocess.check_output([reader, path, provider])
            )
            events, _, state, _ = summary(records(path)[0])

            def meaning(rows):
                return [(e["id"], e["status"], e["label"]) for e in rows]

            assert (state, meaning(events)) == (
                original_sample["worker_state"],
                meaning(original_sample["events"]),
            )
        # Replay successive states of a live source. Backdated timestamps do not
        # reorder the records. A second tool starts before the first finishes.
        live = Path(folder) / "interleaved.jsonl"
        frames = [
            {
                "type": "user",
                "sessionId": "replay",
                "message": {"content": "Check two files"},
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "a",
                            "name": "Read",
                            "input": {"file_path": "a"},
                        }
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "b",
                            "name": "Edit",
                            "input": {"file_path": "b"},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "timestamp": "2020-01-01T00:00:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "a",
                            "content": "x" * 12000,
                        }
                    ]
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "b", "content": "done"}
                    ]
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Both checked"}],
                    "stop_reason": "end_turn",
                },
            },
        ]
        for index, frame in enumerate(frames):
            with live.open("a") as output:
                output.write(json.dumps(frame) + "\n")
            sample = json.loads(subprocess.check_output([reader, live, "claude_code"]))
            events, _, state, _ = summary(records(live)[0])
            assert meaning(events) == meaning(sample["events"]), (index, events, sample)
            assert (state == "finished") == (sample["worker_state"] == "finished"), (
                index,
                state,
                sample,
            )
        files = sorted((ROOT / "examples/launch-review").glob("*.jsonl"))
        reference = original.trace._codex_native_core()
        for detail in (True, False):
            assert reference.render_many(
                [reference.load_rollout(p) for p in files], detail=detail
            ) == (
                codex_native.render_many(
                    [codex_native.load_rollout(p) for p in files], detail=detail
                )
            )
    print(
        "Original and public readers agree on both activity fixtures and both native tree views."
    )


if __name__ == "__main__":
    main()
