# Agent Trace

[![Agent Trace desktop app showing a running Codex chat, its workers and copy controls](docs/images/agent-trace.png)](docs/images/agent-trace.png)

**Let an agent read another Codex chat's commands, outputs and patches without loading the whole transcript.**

Choose a chat, search its recorded activity, and retrieve the output or field you need. Include its workers, keep a reference to what you read, and check what changed as the chats continue running.

This repository contains a Python library and an MCP server for local Codex session files. You register the files it can read. The desktop app shown above uses the same reader and adds automatic discovery, file watching and copy controls.

<a id="what-agent-trace-adds"></a>
<a id="compact-and-detailed"></a>

## What it does

- **Find recorded activity:** search a selected chat and its registered workers by text, item type or recorded failure. Text matches identify the field and passage.
- **Read just what you need:** retrieve one command, output, patch or field. Large values arrive in pages.
- **Keep a stable reference:** repeat a read from the same saved capture, even after the source changes.
- **Follow progress:** retrieve added, updated and removed items since an earlier capture. An unreadable worker is reported as unavailable.
- **Read the conversation:** compact keeps messages, visible thinking summaries, command previews, outcomes and changed paths. Detailed adds inputs, outputs and patches, sharing repeated text and replacing long bodies with previews and retrievable references.

Chat lookup searches registered titles and IDs. Content search runs within the chat you select and, optionally, its workers.

<a id="run-or-inspect"></a>

## Try it

With Python 3.10+, from this checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
.venv/bin/python tools/record_native_contract.py --check --show
```

This searches a recorded development command through the MCP server and prints its retrieved output. [Connect an agent and register your own chats →](docs/mcp.md#setup)

[A real investigation: checking a worker's failed tests, correction and retry →](docs/investigation.md)

## How it works

The reader turns Codex item events into records keyed by session, turn and item ID. The server selects a chat and its workers, saves a capture, then serves searches, fields and comparisons from it. Captures stay available until the server exits; a fresh capture rereads the files.

Start with [the reader](src/trace_mechanism/codex_native.py) and [the retrieval adapter](src/trace_mechanism/agent_tools.py). [The MCP server](src/trace_mechanism/mcp_server.py) defines the callable tools.

[Usage and tool reference](docs/mcp.md) · [How records are processed](docs/mechanism.md) · [Development and repository map](docs/development.md)

<details>
<summary>Inside Codex</summary>

[![Agent Trace plugin inside Codex with chat selection and attach, copy and preview controls](docs/images/codex-plugin.png)](docs/images/codex-plugin.png)

The desktop app's plugin lets you select a chat and attach, copy or preview its context inside Codex. Agents can also retrieve context directly through its tools. This repository contains the reader and standalone MCP server used to inspect the mechanism.

</details>

[Apache-2.0](LICENSE) · Will Cook · [Source provenance](docs/provenance.json) · [Security](SECURITY.md)
