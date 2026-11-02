# Agent Trace: let Codex recover another chat’s context

Agent Trace reads conversation records already saved on your computer, pairs tool calls with results, and exposes compact or detailed views through MCP. An agent can search earlier work, retrieve the relevant thread, and read it again when new records arrive.

This repository contains the parsing code, a runnable MCP server, and the app’s structured-output builder. **Start with the Codex example below.** The desktop app’s discovery and interface are separate.

<details>
<summary>Desktop app screenshot</summary>

[![Agent Trace’s desktop selection interface](docs/images/codex-example.png)](docs/images/codex-example.png)

The rebuilt app, filtered to the same Codex example. Click to inspect the controls and recorded answer. The agent’s retrieval is demonstrated below.

</details>

## A real Codex retrieval

One Codex chat calculated a fictional repair café’s fuse budget. A separate Codex agent received only the source chat ID and a question. Through the installed Agent Trace plugin, it recovered:

> Saturday at 10:00; £21 for seven fuses at £3 each.

The source chat was then told the opening time had changed. A fresh read of the **same compact scope** let the reader answer:

> Saturday at 10:30; the fuse budget is still £21.

Rereading its earlier snapshot returned the original 10:00 text unchanged. The detailed view also included the Python command and its output, `21`.

[Inspect the recording, actual tool requests and limits →](docs/codex-retrieval.md)

## Run the mechanism

Python 3.10+ is required. From a clone:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
.venv/bin/python tools/demo_codex.py
```

This launches a real stdio MCP server, reads the selected recording, supplies its later records, and verifies that a fresh read changes while the old snapshot stays fixed. It needs no model account. It replays retrieval; the recorded Codex agents are not rerun.

**Compact** retains requests, visible assistant messages and selected command/path fields, omitting tool outputs. **Detailed** adds recorded arguments and outputs in source-record order. Neither can recover missing or truncated provider data. Refresh means rereading a file; this example has no watcher.

## Follow the code

| Step | Owner |
|---|---|
| Local records → turns and paired evidence | [parser.py](src/trace_mechanism/parser.py) |
| Turns → compact or detailed text | [views.py](src/trace_mechanism/views.py) |
| Search → fresh read → stable pages | [agent_tools.py](src/trace_mechanism/agent_tools.py), [MCP adapter](src/trace_mechanism/mcp_server.py) |
| Text → source-linked JSON index | [structurer.mjs](src/trace_mechanism/structurer.mjs) |

The provider parsers and JavaScript builder are copied from Agent Trace. The public registry, views and MCP adapter are smaller implementations. The manifest explicitly selects readable files. [Integration and boundaries](docs/mechanism.md) explain how agents use the plugin and skill.

[Reproduce outputs, inspect provenance and run checks](docs/development.md) · [Parser provenance](docs/provenance.json) · [Layout check](tools/check_layout.py)

## The feedback I’m looking for

Before releasing the full app, I’d like advice on the Codex integration: should a local history reader use the documented app-server interface instead of reading session files directly, and which stability expectations should it follow? The useful part here is selecting and reusing recorded context.

[Apache-2.0](LICENSE). Independent software by Will Cook. [Security reporting](SECURITY.md).
