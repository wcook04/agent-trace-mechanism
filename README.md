# Agent Trace

[![Packaged Agent Trace Structurer on macOS showing a synthetic onboarding review, its two workers, copy scopes and the Prompt Shelf](docs/images/agent-trace.png)](docs/images/agent-trace.png)

*The Agent Trace Structurer Mac app is a local technical preview. [Install the app or set up your prompt shelf →](docs/workbench.md)*

**Find a local Codex or Claude Code conversation, follow its workers, and copy the context you want to take into your next chat.**

Open Agent Trace Structurer to browse the conversations already on your computer. Either provider works on its own. Select a conversation, inspect its recorded activity, then preview the parent, individual workers, or the discovered thread before copying. No agent connection is required.

To let an agent retrieve context itself, connect the local **MCP (Model Context Protocol) server** and register the specific files it may read. An agent in either host can then retrieve histories from either provider. Opening a conversation in the workbench never registers it.

<a id="what-agent-trace-adds"></a>

## What it does

For **Codex and Claude Code histories**, an agent can find a selected chat by title or ID and read it in either view:

<a id="compact-and-detailed"></a>

| View | What it returns |
|---|---|
| **Compact** | Messages and tool-call previews, including commands and file paths where recorded. Tool results are omitted. Codex event records also provide visible reasoning summaries, command outcomes and changed paths. |
| **Detailed** | The conversation plus recorded tool inputs and results. For Codex event records, large outputs and patches have previews with references for retrieving the full value; repeated large text blocks appear once, with references where they recur. |

Compact is a filtered transcript, not an AI-written summary. Long responses are split into pages that the agent can request as needed.

<details>
<summary>See the difference on a real recorded command</summary>

<p align="center">
  <img src="docs/images/compact-detailed.svg" width="480" alt="Two views of the same Codex test command. Compact includes its exit status; detailed adds the recorded output showing 124 tests passed and none failed. Selected fields are shown.">
</p>

Both views include the command. Detailed also includes its output. This command pipes the tests through `tail`, so the exit code alone does not establish that the tests passed; the recorded test summary does. The image shows excerpts from [the actual validation history](docs/investigation.md).

An agent can also request just this command's output with `read_trace_item`, selecting the `/aggregated_output` field. It does not have to read the whole detailed conversation.

</details>

For **supported Codex event records**, an agent can also:

- **Find a specific operation:** search commands, outputs, patches and other recorded items by text, type or failure status. Each match identifies the field and matching passage.
- **Read just the relevant evidence:** retrieve one item, such as a command execution, or one field, such as its output. Results include session and item IDs so the agent can identify its source.
- **Include subagents:** search a parent chat and the child chats whose files you have also selected. Parent-child links are checked against the session records.
- **Check what changed:** compare two reads of a running chat to find added, updated or removed items. An unreadable child chat is reported as unavailable.

These queries use structured records of individual Codex operations, called *native items* in the code. They are not yet available for Claude histories or older Codex files that contain only conversation records. An agent in either app can query a supported Codex file.

<a id="run-or-inspect"></a>

## Open Agent Trace Structurer

With Python 3.10+ and a checkout of this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/agent-trace-app
```

This opens the Missions window in your browser. Use it with **Claude Code only,
Codex only, or both**. Click a mission, choose a copy scope, and copy the trace.
**Manage prompts** lets you add your own Markdown prompts. For the native macOS
window or Windows instructions, see [the workbench guide](docs/workbench.md).
The [installable skill](skills/agent-trace/SKILL.md) can set it up for you.

## Try it

With Git and Python 3.10+ (macOS/Linux shell):

```sh
git clone https://github.com/wcook04/agent-trace-mechanism.git
cd agent-trace-mechanism
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
.venv/bin/python tools/inspect_recorded_run.py
.venv/bin/python tools/inspect_agent_tree.py
.venv/bin/python tools/inspect_cross_provider.py
```

These retrieve a real validation history, a Codex review with two subagents, and a Claude review that read their findings through MCP. They print the results without running the recorded commands. No API key, private app or Node installation is needed. [Use your own chats in Codex or Claude →](docs/mcp.md#setup)

[A real investigation: checking a worker's failed tests, correction and retry →](docs/investigation.md)

[A fresh coordinator and two subagents reviewing this repository →](docs/agent-tree.md)

[Claude reads the Codex review, then Codex reads Claude’s findings →](docs/cross-provider.md)

## Let your agent set it up

Give Codex or Claude Code this request:

> Install Agent Trace from https://github.com/wcook04/agent-trace-mechanism on this machine. Read `skills/agent-trace/SKILL.md` and follow its installation guide for my host and environment. Preserve my existing configuration, help me select which histories to register, and verify a real MCP read from my working project.

The [portable skill](skills/agent-trace/SKILL.md) covers setup and using the tools.
To keep it available in future chats, run one of these from the checkout:

```sh
python3 tools/install_skill.py --host codex
python3 tools/install_skill.py --host claude
```

This installs instructions only; it doesn't connect MCP or grant access to any
chat. The [installation guide](skills/agent-trace/references/install.md) covers
project-scoped skills, custom folders, Windows commands and connection checks.

## How it works

Each session file uses JSONL: one JSON record per line.

<p align="center">
  <img src="docs/images/history-flow.svg" width="480" alt="Agent Trace reads selected Codex and Claude Code session files. An agent in either app sends MCP requests and receives selected text with source references.">
</p>

1. **You choose the source files.** A local JSON configuration file, called the manifest, lists the session files the server may read. The server does not automatically add other chats.
2. **Agent Trace parses the records.** For Codex events, it combines updates to the same item ID into that item's latest recorded state. For Claude conversations, it pairs tool calls with their results and groups messages into turns.
3. **The agent requests what it needs.** MCP tools return conversation text, search matches or selected Codex items. The server retains the result of a read in memory as a *snapshot*, so later pages refer to the same version even if the source file grows. A fresh read picks up new records; snapshots last until the server exits.

The public server reads files on request, without changing them or executing the recorded commands. Continuous file watching is part of the desktop app. The requesting host may send retrieved text to its model provider. [Data access and privacy](SECURITY.md).

Start with [the Codex reader](src/trace_mechanism/codex_native.py), [the conversation parsers](src/trace_mechanism/parser.py) and [the retrieval adapter](src/trace_mechanism/agent_tools.py). [The MCP server](src/trace_mechanism/mcp_server.py) defines the callable tools.

[Usage and tool reference](docs/mcp.md) · [How records are processed](docs/mechanism.md) · [Development and repository map](docs/development.md)

<details>
<summary>Inside Codex</summary>

[![Agent Trace plugin inside Codex with chat selection and attach, copy and preview controls](docs/images/codex-plugin.png)](docs/images/codex-plugin.png)

The desktop app's plugin lets you select a chat and attach, copy or preview its context inside Codex. Agents can also retrieve context directly through its tools. This preview of the in-Codex attachment interface is separate from the packaged Missions window and stdio MCP server.

</details>

## Contributing

[Bug reports and pull requests](CONTRIBUTING.md) are welcome. The [development guide](docs/development.md) covers tests and package checks; the [example index](examples/README.md) explains the recordings and generated files. Keep private transcripts out of issues and pull requests.

## Why I built it

I built this while using AI for maths research and making videos and interfaces to help people understand the results.

The reader and workbench are free and open source under the same Apache-2.0 licence.

I'm also sharing this because I'd like more people to see my main projects. You can find them on [my homepage](https://wcook04.github.io/), or start with [the introduction video](https://www.youtube.com/watch?v=MBmVMMogXTA).

Apache-2.0; copyright 2026 Will Cook. Redistributed copies must retain the applicable notices under the licence. If you use Agent Trace in published work, please [cite it](CITATION.cff).

[Licence](LICENSE) · [Attribution](NOTICE) · Will Cook · [Source provenance](docs/provenance.json) · [Security](SECURITY.md)
