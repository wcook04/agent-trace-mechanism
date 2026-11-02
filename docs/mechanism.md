# Reading Codex history

The reader converts local Codex records into messages, commands, tool calls and file changes. The app displays or copies these records; agents can search and read them through MCP.

## Record identity

The [record reader](../src/trace_mechanism/codex_native.py) supports Codex's JSONL session files and the `thread_items` table in its local SQLite database, which it opens read-only. These sources use different field names; the reader converts them to one representation while keeping the session, turn and item IDs. Each item also retains a reference to its source location.

An operation can appear more than once as its state changes. The reader updates the existing item by ID rather than appending another copy. It also omits an outer `functions.exec` wrapper when the operations inside it have their own native records.

Supported types include `CommandExecution`, `FileChange`, `McpToolCall`, `SubAgentActivity`, `UserMessage`, `AgentMessage`, `Reasoning` and `Extension`. Command outcomes come from the exit-code and status fields. The reader does not infer success from words in the output. Reasoning records contribute their visible summaries.

## Views and exact access

Compact retains messages, visible summaries, command previews, outcomes, changed paths and recorded settings. It omits outputs and patch bodies. Detailed includes inputs, outputs and patches, storing repeated text blocks once. Oversized fields have a beginning-and-end preview and a reference containing the session ID, snapshot hash, item ID and field path. The full values remain in the saved records and are included in searches.

`search_trace_items` returns matching records with previews and their session and item IDs. `read_trace_item` reads one item or a selected field, such as `/aggregated_output`. Large values can be read in pages from the same saved version. `read_trace_changes` compares two saved versions and reports added, updated or removed items. Identical repeated records do not appear as changes.

The [index builder](../src/trace_mechanism/structurer.mjs) reads this structured view and produces a JSON index of actions, retaining references into the supplied trace text.

## App and plugin

The desktop app discovers local sessions, watches their files and lets you select which turns to copy. Before reusing a cached view, it checks the renderer version and every selected source file. A change in a subagent's file therefore causes the next read to rebuild the combined view. Recorded parent/child IDs determine which sessions belong together; each session is included once. A missing child's ID is retained even when its records cannot be read.

The installed MCP plugin lets an agent search and read these records without opening the panel. The accompanying [skill](skill-source-excerpt.txt) explains how to find a chat, read a compact view, retrieve individual records and request subsequent changes. Full-thread, latest-response and last-N-turn selections use the same record reader.

The MCP server in this repository reads sessions listed in a manifest. Child entries must match the parent recorded in their session metadata. It rereads selected files on request and keeps saved versions in memory for the life of the server process. The desktop app adds automatic discovery, file watching and storage that persists between runs. Older records without native items use the earlier text parser.

## Codex history API

The inspected desktop runtime, Codex 0.166.0-alpha.5.1, also includes `thread/items/list`, `thread/items/read`, `thread/turns/list` and update notifications through its app-server protocol. Agent Trace currently reads local files. Using a supported history API could replace that file-reading layer while keeping the same views and agent tools.

[Core provenance](provenance.json) · [Builder provenance](structurer-provenance.json) · [MCP configuration](mcp.md)
