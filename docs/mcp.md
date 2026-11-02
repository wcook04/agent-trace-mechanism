# MCP transport demo

The optional server exposes the same search, read and page tool names used by Agent Trace over real MCP stdio. It reads **only files named in a required manifest**, rather than discovering the user's sessions. The manifest is trusted configuration: absolute paths and paths outside its directory are allowed. Transcript contents are returned to the connected client and may contain private information.

Install the optional SDK in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
.venv/bin/python -m unittest discover -s tests -p test_mcp_transport.py -v
```

The test launches the server as a separate process through the MCP SDK client. It initializes a session, lists tools, searches the test threads, reads compact and detailed views, appends records, and checks that old pages remain stable while a new read sees the update. It creates its inputs in a temporary directory and does not access a model or account.

For a host integration, create a JSON manifest that explicitly names the files it may expose. Paths can be absolute or relative to the manifest file:

```json
[
  {"provider": "codex", "session_id": "sample-codex", "title": "Sample Codex thread", "path": "codex.jsonl"}
]
```

Launch it via the host's MCP stdio configuration, with the executable and arguments equivalent to:

```sh
.venv/bin/python -m trace_mechanism.mcp_server --manifest /absolute/path/to/manifest.json
```

The host calls `search_trace_threads`, then `read_chat_context` with the chosen provider and session ID. Scope `full_thread_concise` is compact; `full_thread` includes recorded detail. If `next_offset` is present, pass it and `sha256` to `read_trace_page`. Snapshots live in the server process and disappear when it exits. A fresh read reparses the selected file; there is no watcher.

This is an adapter around the public example's parser and views. Its registry, snapshots and rendering are smaller than the production app's discovery, richer renderers, linked-child handling and MCP interface. It does not install a skill, call a model or establish that either host has been configured. The underlying provider records determine what can be returned; unavailable or truncated content cannot be reconstructed.
