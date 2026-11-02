# Reading and retrieving Codex records

Agent Trace has two processing paths. The native reader consumes recorded item events and powers item search, field retrieval and change queries. The legacy parser reads older transcript records. The JavaScript builder indexes supplied rendered text; it is a separate export tool, not a second database behind the native MCP calls.

## Inputs and coverage

The public server accepts explicitly registered JSONL files. Its native reader processes `event_msg` records containing supported `item_started`, `item_updated` and `item_completed` items. It retains the session, turn and item IDs and the source record positions. Later events replace the state of an existing item ID while preserving its source references.

Supported items cover user and assistant messages, visible reasoning summaries, commands, file changes, MCP calls, child-agent activity and recorded web searches. Field names and item types are normalized across the supported wire shapes. Command status and exit code come from recorded fields; words inside output do not determine success. `aggregated_output` contains the recorded combined stdout and stderr.

The native path excludes outer `response_item` records. This is an admission rule, not a test proving each excluded wrapper has a complete native equivalent. Unsupported native items and malformed records appear in diagnostics. Encrypted fields are excluded, and reasoning contributes only its recorded visible summary. Nothing in a detailed view can recover content absent from the retained source.

When a selected session has no supported native items, conversation views use the legacy transcript parser. Native item search does not turn legacy wrapper text into native items.

The library also has `load_history`, a read-only reader for rows in SQLite's `thread_items` table. It is **not a public MCP manifest option**. It reads rows for one physical thread ID; it does not implement Codex's fork-lineage and segment traversal. Codex's [logical history reader](https://github.com/openai/codex/blob/dd2df0aa9d7ae3667236d6f9feeea03c8e544d7a/codex-rs/thread-store/src/local/thread_history/segment_paging.rs) applies those additional rules. The library function therefore does not claim equivalence to the history returned by App Server.

## Normalized records and views

The saved native representation is decoded JSON with normalized field names, supported content and source references. A read returns that retained representation or a field within it. It does not return the original JSONL bytes. For example, `aggregatedOutput` is read through `/aggregated_output`.

Compact keeps messages, visible summaries, command previews and outcomes, changed paths and settings. Detailed adds retained inputs, outputs and patches. Long values use previews and references; equal text blocks share one copy across a rendered parent/child selection. Full retained values remain available to item search and field reads.

These are separate operations:

| Operation | What it removes or combines |
|---|---|
| Update an item by ID | Earlier states of that same recorded operation in the current view |
| Visit a session once | Duplicate traversal of the same registered chat |
| Share equal text blocks | Byte-identical text repeated in the rendered selection |
| Exclude outer wrappers | All outer `response_item` records from the native path |

None of these establishes that inherited history appearing in different forked sessions has been included only once.

## Captures, references and freshness

A capture holds the selected root and readable children. The files are read sequentially and the assembled result is then fixed. It is immutable for later reads, but is not a simultaneous transaction across those files.

`read_chat_context`, `search_trace_items` and `read_trace_changes` return a `snapshot_sha256` for that capture. It can be reused for searches, item reads and change comparisons. Rendered text has a separate `text_sha256`; use that with `read_trace_page`. Core hashes inside large-field references identify the retained session snapshot. The [MCP guide](mcp.md) defines each parameter and paging unit.

Fresh context and item-search calls reread the selected files. Change queries also compare retained item identities and normalized item values against an earlier capture. Source-reference or lifecycle-timestamp changes alone do not count as an item update. These are on-demand reads, not a notification subscription or incremental file parser. Fixed pages do not reread their sources. Saved versions last for the server process; restarting the public server invalidates its stored references.

## Parent and child sessions

The public server follows `parent_session_id` relationships among explicit manifest entries, checked against the child's recorded parent ID. It does not infer relationships from titles or nearby timestamps. Search, context and change queries can include registered descendants, up to 64 selected sessions.

A missing child is reported as unavailable while available sessions remain readable. A missing root is an error. Unavailability is distinct from proof that its items were deleted. Fresh public-server requests reload the manifest and can include newly registered children. They do not discover unregistered files on the computer.

The desktop app adds automatic local-session discovery, file watchers and persistent storage. Before reusing a prepared view, it checks the selected source files, including children, and its renderer version. Its latest-response and last-N-turn copy scopes are additional app functions; this public server supplies compact and detailed full-thread views.

The full app's plugin also includes a skill. This package supplies its own [six-tool usage instructions](mcp.md); it does not install that desktop plugin. Retained production excerpts describe their captured source versions, not the public server's current callable interface.

## Codex history interface

The question is how a separate reader should receive updates for a chat executing in the desktop app. There is no demonstrated requirement here to bypass supported history reads.

On 2 November 2026, a new App Server process from the installed Codex `0.166.0-alpha.5.1` runtime successfully read this running desktop chat with `experimentalApi: false`:

| Call | Observed result |
|---|---|
| `thread/read` | Stored metadata; runtime status `notLoaded` in the new process |
| `thread/turns/list`, `limit: 1`, `itemsView: "full"` | One persisted turn and history cursors |
| `thread/items/list`, `limit: 1`, descending | One persisted item and history cursors |

The probe did not start or resume a turn, subscribe to events, or change the desktop chat. These results establish stored-history access from a second process; they do not establish delivery of future notifications from the process running the chat.

The [official App Server guide](https://developers.openai.com/codex/app-server/) describes stored-history paging without resuming. In the inspected [protocol declaration](https://github.com/openai/codex/blob/dd2df0aa9d7ae3667236d6f9feeea03c8e544d7a/codex-rs/app-server-protocol/src/protocol/common.rs), `thread/items/read` is experimental, whereas `thread/items/list` and `thread/turns/list` have no experimental annotation. They should not be presented as one stability contract.

A useful answer would identify the intended passive observation route: should a separate local client poll persisted history, or can it subscribe to updates from the desktop-owned thread without resuming it? That is the requested integration guidance, not a request to review the application or approve its release. The current file reader can be replaced while retaining Agent Trace's selection, views and saved-reference layer.
