# Native Codex record pipeline

`local records → canonical native items → selected views / item queries → MCP`

## Record identity

The portable [core](../src/trace_mechanism/codex_native.py) consumes typed native events from Codex JSONL and the read-only `thread_items` SQLite projection. It normalizes the JSONL/SQLite naming conventions and keeps exact session, turn and item IDs. Updates replace the earlier representation of that item; source references retain the record locations. Outer `functions.exec` wrappers are not copied over the native operations they contain.

Supported types include `CommandExecution`, `FileChange`, `McpToolCall`, `SubAgentActivity`, `UserMessage`, `AgentMessage`, `Reasoning` and `Extension`. Command status uses typed exit/status fields. Quoted output cannot turn a failure into a pass. Reasoning contributes its recorded visible summaries.

## Views and exact access

Compact retains messages, visible summaries, command previews, outcomes, changed paths and useful settings. It omits outputs and patch bodies. Detailed expands evidence, shares repeated bodies and gives oversized fields bounded previews with exact retrieval references. The underlying native snapshots retain the full captured payloads; searches inspect those full values.

`search_trace_items` returns small handles, including the item's own session ID and native item ID. `read_trace_item` opens one item or selected field, with stable paging for large values. `read_trace_changes` compares immutable captures and reports added, updated or removed items. Repeated identical lifecycle records do not count as new work.

The [index builder](../src/trace_mechanism/structurer.mjs) consumes the typed native view directly, retaining references into the original text. It does not guess command outcomes from stdout.

## App and plugin

The desktop app discovers local sessions, watches activity and provides copy/export scopes. Its native cache checks the renderer version and every selected source, so a worker advancing can invalidate a cached parent view. Exact recorded parent/child IDs build the tree; a session appears once. Missing child sources remain identifiable.

The installed MCP plugin exposes retrieval without requiring the panel. The accompanying [skill](skill-source-excerpt.txt) teaches selection, compact-first reading, exact evidence retrieval and incremental reads. Full-thread, latest-response and last-N-turn scopes use the same native core.

This public adapter uses an explicit manifest instead of the app's discovery. Child entries must match the parent recorded in their session metadata. It rereads selected files on request and keeps snapshots for the server process. The app owns live watchers and persistent storage. Older records retain the legacy parser route.

## Integration surface

These are local records owned by the user. The inspected desktop runtime also exposes `thread/items/list`, `thread/items/read`, `thread/turns/list` and update notifications through its app-server protocol. The present implementation reads local JSONL / SQLite; a supported protocol adapter is a possible next integration.

[Core provenance](provenance.json) · [Builder provenance](structurer-provenance.json) · [MCP configuration](mcp.md)
