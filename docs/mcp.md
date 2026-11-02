# Agent interface

Install Python 3.10+ and the MCP extra:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
```

Create a JSON manifest listing the files the server may read. Use the actual `session_meta.id` for native Codex records:

```json
[
  {"provider": "codex", "session_id": "ACTUAL_THREAD_ID", "title": "My work", "path": "/absolute/path/to/rollout.jsonl"}
]
```

Launch via the host's stdio MCP configuration:

```sh
.venv/bin/python -m trace_mechanism.mcp_server --manifest /absolute/path/to/manifest.json
```

| Tool | Access |
|---|---|
| `search_trace_threads` | Find a registered chat by title or ID |
| `search_trace_items` | Search full native values, filter kind/failures, optionally include children |
| `read_trace_item` | Retrieve one exact item or field from the selected immutable snapshot |
| `read_trace_changes` | Added, updated and removed items since a previous native snapshot |
| `read_chat_context` | Compact (`full_thread_concise`) or detailed (`full_thread`) text |
| `read_trace_page` | Continue a fixed text snapshot |

Item searches return `snapshot_sha256`, exact `session_id` / `item_id` handles and `next_offset`. Reuse the snapshot hash for subsequent search or item pages. A child's item must be read using the child's session ID. For incremental reads, pass the earlier hash as `since_sha256` and keep the same `include_children` setting.

Use `field="/aggregated_output"` to read only stdout, or a JSON Pointer such as `/changes/escaped-file-path/unified_diff` for a patch. An empty field selects the complete item. Use the exact pointer supplied by a large-payload reference.

A manifest child can include `parent_session_id`. The server verifies it against that child's recorded `session_meta.source.subagent.thread_spawn.parent_thread_id`; titles do not establish a relationship. Trees are capped at 64 selected sessions.

Text pages use their separate `sha256` identifier. Snapshots last for the server process; each fresh read checks the selected files again. The app supplies automatic discovery, persistent snapshots, watchers and additional recent-turn scopes.
