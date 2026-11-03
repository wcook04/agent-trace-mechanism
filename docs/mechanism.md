# How it works

[Usage](mcp.md) · [Development](development.md) · [README](../README.md)

Agent Trace reads local session files and returns selected parts to an agent through MCP. You list the permitted files in a manifest. Both Codex and Claude Code histories can be read as conversations; supported Codex event records also allow queries for individual commands, outputs, patches and changes between reads.

A *native item* is one structured Codex record, such as a command execution. A *snapshot* (also called a capture below) is the parsed data or rendered conversation retained from a read. It lets the agent request more pages of the same version while the original file continues to grow.

The source files use JSONL: one JSON record per line. [The README diagram](../README.md#how-it-works) shows how those files reach the requesting agent.

<a id="inputs-and-coverage"></a>

## Codex event records

The native reader processes `event_msg` records containing supported `item_started`, `item_updated` and `item_completed` items. It retains session, turn and item IDs and source record positions. A later event updates the same item while preserving its source references.

Supported items include messages, visible reasoning summaries, commands, file changes, MCP calls, child-agent activity and recorded web searches. Field names and item types are normalized across supported wire shapes: for example, `aggregatedOutput` becomes `/aggregated_output`. Command status and exit code come from recorded fields; output wording does not determine success. Aggregated output contains the recorded combined stdout and stderr.

Reads return decoded, normalized values, rather than original JSONL bytes. Encrypted fields and outer `response_item` wrappers are excluded. Unsupported native items and malformed records appear in diagnostics. Excluding wrappers does not establish that each has a complete native equivalent.

If a session has no supported native items, conversation views use the legacy transcript parser. Native item search still searches only native items. The separate JavaScript builder indexes rendered trace text; it is not part of this native retrieval path.

## Claude conversation records

The Claude parser groups user messages, assistant messages and tool activity into turns. It matches each tool result to its call ID and marks missing calls or results. The server checks that the file's recorded session ID matches its manifest entry. Compact views omit tool results and keep selected call arguments; detailed views include recorded inputs and results. Both views can be read in pages from a retained text snapshot.

Claude histories do not currently support native item queries, snapshot comparisons or automatic child traversal. Register a Claude worker as a separate history when it has its own recorded session ID.

<a id="normalized-records-and-views"></a>

## Codex compact and detailed views

Compact includes messages, visible reasoning summaries, command previews and outcomes, changed paths and settings. Detailed adds retained inputs, outputs and patches. Long values have previews and field references; the full retained values remain searchable and retrievable.

The renderer visits each selected session once and shares identical text blocks across the selection. Updating an item by ID keeps its latest recorded state. These operations do not deduplicate inherited history across different forked sessions.

## Captures, references and freshness

A capture saves the selected root and readable children. Files are read sequentially, then the assembled result is fixed. Later reads see that fixed result, not a simultaneous transaction across all source files.

Native calls return `snapshot_sha256` for searches, item reads and comparisons. Rendered text has a separate `text_sha256` for text pages. Large-field references can identify a single session snapshot. [Handle and paging reference](mcp.md#paging-and-saved-versions).

Fresh calls reread files. Comparisons report changes to item identities and normalized values; source positions or lifecycle timestamps alone do not count as item updates. Saved pages do not reread files. Captures are held in memory until the public server exits. This server performs on-demand reads; it does not subscribe to notifications or parse file additions incrementally.

## Parent and child sessions

The adapter follows manifest `parent_session_id` links, verified against each child's recorded parent ID, for up to 64 selected sessions. It does not infer links from titles or timestamps. Fresh requests reload the manifest, including newly registered children.

An unavailable child is reported alongside readable sessions. A missing root is an error. An unreadable child's items are not treated as deleted. A readable child's parent must match the manifest before its content can be returned.

The desktop app adds discovery, watchers, persistent captures and recent-turn copy scopes. Before reusing a prepared view, it checks source files, children and the renderer version. The public server uses explicit files, process-local captures and full-thread views.

## Codex history interface

Codex provides stored-history APIs through [App Server](https://developers.openai.com/codex/app-server/). This package currently reads JSONL; App Server is not a configured input. In the inspected [protocol version](https://github.com/openai/codex/blob/dd2df0aa9d7ae3667236d6f9feeea03c8e544d7a/codex-rs/app-server-protocol/src/protocol/common.rs), `thread/items/read` is experimental; `thread/items/list` and `thread/turns/list` have no experimental annotation.

The library's read-only SQLite function, `load_history`, is not a public MCP input option. It reads `thread_items` rows for one physical thread ID. It does not implement Codex's [logical fork and segment traversal](https://github.com/openai/codex/blob/dd2df0aa9d7ae3667236d6f9feeea03c8e544d7a/codex-rs/thread-store/src/local/thread_history/segment_paging.rs), so its results are not equivalent to App Server history.
