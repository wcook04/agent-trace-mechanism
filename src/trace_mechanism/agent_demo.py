"""Legacy Codex fixture smoke test; use tools/demo_codex.py for the recorded MCP example."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from .agent_tools import AgentTools
from .replay import records


def write_records(path, events, mode):
    with path.open(mode) as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")


def main():
    with TemporaryDirectory() as directory:
        entries, pending = [], {}
        for provider in ("codex",):
            path = Path(directory) / (provider + ".jsonl")
            initial, later, _ = records(provider)
            write_records(path, initial, "w")
            pending[provider] = (path, later)
            entries.append({"provider": provider, "session_id": "synthetic-" + provider,
                            "title": provider + " example investigation", "path": path})
        tools = AgentTools(entries)
        for caller, source in (("test_client", "codex"),):
            found = tools.search_trace_threads(source + " investigation")[0]
            before = tools.read_chat_context(source, found["session_id"])
            path, later = pending[source]
            write_records(path, later, "a")
            after = tools.read_chat_context(source, found["session_id"])
            detailed = tools.read_chat_context(source, found["session_id"], "full_thread")
            old_page = tools.read_trace_page(before["sha256"])
            print(json.dumps({
                "test_client": caller,
                "source_provider": source,
                "source_thread": found["session_id"],
                "compact_before_append": before["text"],
                "compact_after_append": after["text"],
                "detailed_after_append": detailed["text"],
                "new_snapshot": before["sha256"] != after["sha256"],
                "old_snapshot_unchanged": old_page["text"] == before["text"]
            }, indent=2))


if __name__ == "__main__":
    main()
