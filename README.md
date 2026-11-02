# Agent Trace

[![Agent Trace showing live Codex activity, linked workers and copy scopes](docs/images/agent-trace.png)](docs/images/agent-trace.png)

Agent Trace reads the conversation history that Codex stores on your computer, including the commands, tool calls and file changes recorded during each chat. You can browse that history in a desktop app, copy a selected part of it, or let an agent retrieve it through an MCP server.

An agent can search another chat, read a command's output, inspect a patch or check a subagent's progress without someone copying the conversation into its context. It can also retrieve new records while the other chat is still running.

## What you can read

| Records | Contents |
|---|---|
| Conversation | User messages, assistant updates, final answers and visible thinking summaries |
| Commands | Command arguments, working directory, recorded status, exit code, duration and output |
| File changes | File paths and the recorded patch for each change |
| Tool calls | MCP tool names, arguments and results, plus recorded web operations |
| Subagents | Parent and child chat IDs, activity records and each available child's conversation and tool history |
| Settings | Recorded model, reasoning-effort and working-directory changes |

You can select the full thread, the latest response or a number of recent turns. Including subagents follows the parent/child relationships recorded by Codex, so each chat is included once.

## Compact and detailed views

**Compact** keeps messages, visible thinking summaries, command previews, command status and changed file paths. It leaves out command output and patch bodies.

**Detailed** adds inputs, output and patches. Repeated text blocks share one copy. Large fields have a beginning-and-end preview, their full length, and a reference that an agent can use to retrieve the complete field. This keeps long source-file reads, browser results and tool output from filling the copied thread.

The full captured fields remain available for search and retrieval. A reference identifies the chat, the saved version of its records, the item and the field, so it still retrieves the same content after the live chat changes.

## Access from an agent

The plugin includes an MCP server and a skill describing how to use its tools. An agent can:

- Find a chat by title or ID with `search_trace_threads`.
- Search commands, output text, patches and visible summaries with `search_trace_items`, filtering by record type or failed status and optionally including subagents.
- Read one item, or one field such as command output, with `read_trace_item`. Large values can be read in pages.
- Request only added, updated or removed items since an earlier read with `read_trace_changes`.
- Read a compact or detailed conversation with `read_chat_context`, continuing through `read_trace_page` when needed.

## How it works

1. **Read Codex's records.** The reader supports local JSONL session files and the SQLite history format. The app currently reads session files and watches for changes.
2. **Identify each recorded operation.** The reader keeps Codex's thread, turn and item IDs. A later update to an item replaces its earlier state. Command outcomes come from the recorded exit code and status; file changes come from the recorded patches.
3. **Build the requested view.** Compact and detailed views use those items in recorded order. When a tool-call wrapper contains operations that Codex also records individually, the reader avoids including both copies. Repeated text is stored once across the selected parent and child chats.
4. **Keep reads consistent.** The app stores fixed copies of the records used for a view. Later pages and field requests refer to that saved copy. A fresh read can then report what changed. The app also checks linked child sources before reusing a cached view.

## Code in this repository

This repository contains the app's native record reader and structured-index builder, plus a smaller MCP server that reads files listed in a manifest. The desktop app adds session discovery, file watchers, copy controls and persistent storage.

| Code | Responsibility |
|---|---|
| [Record reader](src/trace_mechanism/codex_native.py) | Parse native items, build views, retrieve fields and compare saved records |
| [Agent tools](src/trace_mechanism/agent_tools.py) | Select chats and children, search records and serve saved versions |
| [MCP server](src/trace_mechanism/mcp_server.py) | Make those operations callable by agents |
| [Index builder](src/trace_mechanism/structurer.mjs) | Produce a JSON index of actions with references into the supplied trace text |

[How the records are processed](docs/mechanism.md) · [MCP setup](docs/mcp.md) · [Development](docs/development.md) · [Source provenance](docs/provenance.json) · [Layout check](tools/check_layout.py)

Feedback on which Codex history interface to build against would be useful before I release the full app.

[Apache-2.0](LICENSE) · Will Cook · [Security](SECURITY.md)
