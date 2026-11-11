# Agent Trace

Find a local **Codex or Claude Code conversation**, see what its workers actually ran, and take just the context you need into your next chat. Agent Trace opens in your browser or a native Mac window and reads recordings already on your computer. Either provider works on its own.

[![A test worker’s pytest command exited with code 1. Its output shows expected 8.25, got 8.24. A git diff and a second pytest run follow.](docs/images/agent-trace.png)](docs/images/agent-trace.png)

In this example the checkout total was off by a cent. Click the first **pytest** tile to see the failed assertion, **git** to see the rounding change, and the second **pytest** to see the test pass. Back in the parent conversation, **Choose sessions…** lets you copy the investigation and its test worker while leaving out the documentation worker. [Try the synthetic recording](#try-the-example).

[Introduction to the projects](https://www.youtube.com/watch?v=Yk_kUQUCylc) · [Agent Trace walkthrough](https://www.youtube.com/watch?v=gkjescasrbY) · [Short demo](https://www.youtube.com/watch?v=LbNzdh5pLZ8)

## Try it

From a terminal on macOS or Linux, with Git and Python 3.10 or later installed:

```sh
git clone https://github.com/wcook04/agent-trace-mechanism.git
cd agent-trace-mechanism
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/agent-trace-app
```

On Windows, clone the repository and run these commands in PowerShell from its directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\agent-trace-app.exe
```

The workbench opens on this computer. Its **Missions** list contains recorded conversations and agent runs, including archived Codex chats. Open **History folders** to choose a custom provider home. **Hide from list** changes the workbench view. **Archived in Codex** describes where Codex stored the recording.

**On a Mac**, the native window adds a floating capsule and system pasteboard. From the same checkout, install the desktop extra and launch it:

```sh
.venv/bin/python -m pip install '.[desktop]'
.venv/bin/agent-trace-app --desktop
```

The current release is a technical preview. The native window is available from source. A notarized Mac download is pending. [Workbench guide](docs/workbench.md) · [Release files](https://github.com/wcook04/agent-trace-mechanism/releases).

## Try the example

Open **History folders**, set **Codex home** to the absolute path of [examples/checkout-review](examples/checkout-review) in your clone, and save. Select **Investigate a checkout total**, choose **Test runner**, then **Open thread**. Clicking a command shows its recorded outcome, an output excerpt when available, and its location in the source file. Clear the folder setting to return to your own histories.

**Preview copy** lists the sources and shows the exact text. **Copy this text** copies that snapshot even if another event arrives. **Refresh + Copy** reads the recordings again. Compact views omit tool bodies. Detailed views can excerpt large native outputs. You can also select unrelated recordings together or save a personal Markdown prompt on the prompt shelf.

## Let an agent read selected files

For a one-off handoff, paste the preview into your next chat. For repeated queries, the optional **MCP server** lets Codex or Claude Code read only the files you explicitly register. Browsing, previewing, or pinning a chat grants no MCP access. A connected host may send retrieved text to its model provider.

Install the extra, then list local recordings:

```sh
.venv/bin/python -m pip install '.[mcp]'
.venv/bin/python -m trace_mechanism.setup list --provider codex
```

Follow the [registration and host connection guide](skills/agent-trace/references/install.md) or give your agent the [installation skill](skills/agent-trace/SKILL.md). A host can search registered recordings, read an exact selection by recording ID, or page through a native Codex command’s output. [MCP tools and examples](docs/mcp.md) · [Data access and privacy](SECURITY.md).

## Explore and contribute

- [Example recordings](examples/README.md) include a failed test investigation, a coordinator with two workers, and a cross-provider review.
- [How the reader works](docs/mechanism.md) and [reader provenance](docs/provenance.json) describe the supported formats and their origins.
- [Development and source map](docs/development.md) and [contributing](CONTRIBUTING.md) cover local checks, packaging and reporting bugs.

[Apache 2.0 licence](LICENSE) · [Attribution](NOTICE) · [Cite Agent Trace](CITATION.cff)
