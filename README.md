# Agent Trace

Agent Trace lets an agent search recorded Codex activity in other chats, retrieve a particular command output or patch, and read what changed while those chats continue running. It also provides compact and detailed views for people to browse or copy.

**This repository contains the record reader and a runnable MCP server.** The desktop app uses the same reader and adds session discovery, file watching, copy controls and persistent snapshots. The public server reads JSONL files you explicitly register; it keeps snapshots for the life of its process.

**The integration question:** what is the recommended way for a separate client to observe new persisted items in a chat that the Codex desktop app is running, without resuming it? Read-only history calls already work in our local check. The remaining question is how that client should receive updates. [Methods checked and exact scope](docs/mechanism.md#codex-history-interface).

<details>
<summary>Desktop app screenshot</summary>

[![Agent Trace desktop app: running chats, linked workers and selectable copy scopes](docs/images/agent-trace.png)](docs/images/agent-trace.png)

The supplied screenshot shows the full desktop app at an earlier revision. Its copy sizes describe whole exports, not what an MCP call puts in an agent's context. The server below returns bounded search results, text pages or selected fields.

</details>

## What Agent Trace adds

Codex already records messages, visible thinking summaries, commands, tool calls, file changes and child-thread activity. Agent Trace makes those records available through the following operations:

| Operation | Returned information |
|---|---|
| Search within a chat and its registered children | Matching item IDs, recorded status, and a short passage identifying the matching field |
| Read a command, patch or tool result | One captured item or a field selected by JSON Pointer, with paging for large values |
| Read another chat's context | A compact or detailed view, optionally including registered children |
| Check for changes | Paged added, updated and removed item references between two fixed captures |
| Continue an earlier read | The same saved content, even after the source file changes |
| Follow recorded parent/child links | Each selected session once, with explicit availability information when a child cannot be read |

These operations use Codex's session, turn and item IDs. An agent can request an output directly without receiving the rest of the conversation. [A complete request and response from an actual recorded test command](examples/native-command-response.json) shows the returned contract; [the MCP guide](docs/mcp.md) explains how to use it.

## Compact and detailed

**Compact** keeps messages, visible thinking summaries, command previews and status, changed file paths and recorded settings. It omits command output and patch bodies.

**Detailed** adds inputs, outputs and patches. Identical text blocks share one copy. Fields over the inline limit have a beginning-and-end preview, their length and an item/field reference. The full retained value remains searchable and retrievable from that snapshot. Detailed text is therefore a view of the records, not a self-contained copy of every field.

Text and field reads default to 24,000 characters and accept up to 48,000 per page. Item search and change results default to 20 items and accept up to 100. Callers choose the next page rather than receiving the entire history at once. [Paging units and snapshot lifetime](docs/mcp.md#paging-and-saved-versions).

## How it works

1. **Read recorded items.** The JSONL reader processes supported item-start, update and completion events. It normalizes field names and retains their session, turn and item IDs. Later events for the same item update its state.
2. **Select the history.** The adapter follows verified parent/child IDs among registered files. It reads each source, then freezes the assembled result. Sources are read sequentially; the capture does not claim that all workers were observed at the same instant.
3. **Search or render.** Searches inspect retained fields, including long outputs. Compact and detailed views use the same normalized records. Outer `response_item` wrappers are excluded from this path; older transcripts without supported native items use the legacy parser.
4. **Read by reference.** A snapshot hash selects a saved capture; a session ID, item ID and optional field path select the value. Later pages use that capture. A fresh read rereads the files and can report changes against it.

The Python reader powers these MCP calls. The JavaScript index builder is a separate consumer of rendered trace text; it is not required to search native items. [Record coverage, deduplication and consistency](docs/mechanism.md).

## Run or inspect

Python 3.10+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
.venv/bin/python tools/record_native_contract.py --check
```

The check sends requests through the actual stdio MCP server using the selected recorded command. It compares the responses with the linked capture; it does not rerun the command in the recording. To read your own chats, follow [manifest setup](docs/mcp.md).

| Source | Responsibility |
|---|---|
| [Record reader](src/trace_mechanism/codex_native.py) | Normalize recorded items, render views, search fields and compare item states |
| [Agent tools](src/trace_mechanism/agent_tools.py) | Select registered sessions, assemble captures and serve bounded reads |
| [MCP server](src/trace_mechanism/mcp_server.py) | Tool schemas and stdio transport |
| [Index builder](src/trace_mechanism/structurer.mjs) | Index actions and source ranges in supplied trace text |

[Development and tests](docs/development.md) · [Source provenance](docs/provenance.json) · [Layout check](tools/check_layout.py)

[Apache-2.0](LICENSE) · Will Cook · [Security](SECURITY.md)
