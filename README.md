# Agent Trace: context across Codex and Claude Code

[![Agent Trace showing Codex and Claude Code threads, live parent and subagent activity, and compact and detailed copy scopes](docs/images/agent-trace.png)](docs/images/agent-trace.png)

*The full Agent Trace app. Click the screenshot to inspect it at full resolution.*

**With Agent Trace configured in both hosts, Codex can read a running Claude Code thread, and Claude Code can read a running Codex thread. Either can retrieve a compact earlier thread, then request a detailed view.**

That is what my Agent Trace app and local MCP plugin do. This repository makes the mechanism inspectable: it reuses the app's actual provider parsers, demonstrates search and refresh with synthetic conversations, and includes a selected, sanitized recording of a real Terra parent and two Luna agents checking this repository. It is a runnable extraction and explanation, not the full app.

## See it in a minute

**Start with the real run:** [compact conversation and commands](examples/controlled-run/assembled.compact.txt) → [detailed tool inputs and outputs](examples/controlled-run/assembled.detailed.txt) → [structured attachment index](examples/controlled-run/structured-attachment.json). Terra asked two Luna agents to check the repository, then independently checked their evidence. You can see what they read, the checks they attempted, their corrections and the results. The [sample guide](docs/controlled-run.md) explains the selection and links the JSON index's required raw sidecar. This is a Codex-hosted run; the Claude examples below use invented records.

For smaller examples you can run yourself:

1. Compare the same Codex thread in [compact form](examples/codex.compact.txt), [full detail](examples/codex.detailed.txt), and [structured JSON](examples/codex.expected.json).
2. Compare the Claude Code thread in [compact form](examples/claude.compact.txt), [full detail](examples/claude.detailed.txt), and [structured JSON](examples/claude.expected.json).
3. Read the [agent-facing search/read boundary](src/trace_mechanism/agent_tools.py): select a provider, session and scope; read again after more records arrive.
4. Inspect the [actual structured attachment exhibit](examples/production-structured-clip.json) and its [builder logic](docs/structured-clip-source-excerpt.txt). It stores source text once and adds indexes pointing into it.
5. Run the [two-way live example](src/trace_mechanism/agent_demo.py). It models Codex reading Claude's file and Claude reading Codex's file before and after new events arrive. No model or account is needed.

“Compact” and “detailed” are two views of the **same thread**.

| Scope | What an agent gets |
|---|---|
| **Full thread compact** | Prompts, final assistant text, tool names, commands and file paths. Tool-result bodies and edit contents are omitted. Useful for recovering context across earlier chats. |
| **Full thread detailed** | Available recorded prompts, assistant text, tool arguments and results, including text returned by file reads and old/new text supplied to edits. Useful for inspecting evidence behind a previous answer. |
| **Structured JSON** | Turns containing paired tool calls/results, completion state and explicit missing-result markers. Usable by code as well as another agent. |

These small renderers illustrate the distinction. The full app also retains chronological progress, richer provenance, linked-agent records and navigation indexes. The [implementation boundary](docs/mechanism.md) identifies what is copied and what is adapted here.

## How an agent uses it

In the full app, the same local MCP server can be configured in both Codex and Claude Code. Each host must have the server enabled and the retrieval skill available. The skill tells the agent to search for a thread, verify its identity and select the required scope. Neither the picker nor manual copy/paste is required.

A Codex agent can search for a Claude investigation, read its compact thread, then request detail about recorded commands. A Claude agent uses the same tools against a Codex thread. The calling model does not change the parser; the selected source provider does.

- [Actual MCP registration and scope-selection excerpts](docs/mcp-source-excerpt.txt)
- [Actual context-retrieval skill excerpt](docs/skill-source-excerpt.txt)
- [How the plugin and hosts connect](docs/mechanism.md#plugin-and-skill)

The runnable example uses the same tool names:

```python
found = tools.search_trace_threads("claude investigation")[0]
compact = tools.read_chat_context("claude", found["session_id"], "full_thread_concise")
detailed = tools.read_chat_context("claude", found["session_id"], "full_thread")
# If a response has a next_offset, continue that immutable snapshot:
if detailed["next_offset"] is not None:
    page = tools.read_trace_page(detailed["sha256"], detailed["next_offset"])
```

The last call applies only when `next_offset` is not `None`. A fresh `read_chat_context` call reads the growing source again.

This review repository models those calls in Python. It does not register an MCP server, install the plugin or call either model.

## Run the examples

Requires Python 3.10 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m trace_mechanism.agent_demo
.venv/bin/python -m trace_mechanism codex examples/codex.jsonl --view compact
.venv/bin/python -m trace_mechanism codex examples/codex.jsonl --view detailed
.venv/bin/python -m trace_mechanism claude examples/claude.jsonl --view json
.venv/bin/python -m unittest discover -s tests -v
python3 tools/check_layout.py
```

The agent demo writes invented records to temporary files, reads them, appends a result and reads again. Both providers demonstrate a pending call becoming complete. Existing pages still refer to the old snapshot; a fresh read produces a new snapshot.

“Live” means reading what the other client has already saved locally. The native app uses filesystem watchers and refresh; the MCP panel refreshes periodically, and agent reads retrieve a new snapshot. This example uses explicit rereads, not a background watcher or a provider event stream.

Parsing needs only Python's standard library. Installation uses setuptools and may download it. The examples do not scan your home directory, connect to a provider, use credentials or execute commands found in transcripts. The CLI reads only the file you name.

## What is accessible, and why I want feedback

A conversation record can contain more than the final answer. If an agent reads a file, the tool result can contain the file's text. Commands, arguments, error logs and edit bodies can also be recorded. A detailed export makes that material easier to inspect, copy and reuse.

I built Agent Trace to recover context across my work. My release question is about the boundaries around making these transcripts easy to export and reuse across providers, including possible dataset or training uses. I would like to understand any relevant restrictions before releasing the full tool. This example demonstrates the mechanism; it does not establish permission for a particular use.

| Boundary | What happens |
|---|---|
| Source | Local persisted Codex or Claude Code records supplied by the caller; no access to an internal OpenAI or Anthropic service. |
| Contents | Only records present in the file and supported by the parser. Missing events and unrecorded model reasoning are not reconstructed. |
| Sensitive material | File contents or secrets can be present in tool results. This extraction does **not** redact them. The small fixtures are synthetic; the controlled real run was separately selected and sanitized before inclusion. |
| Agent access | In the full plugin, returned text becomes available to the calling agent. Reading across providers can put the source thread's contents into the other provider's model context. |
| Publication | The supplied app screenshot and deliberately controlled run are included. The run has a selection receipt; unrelated conversation bodies and credentials are excluded. |

Codex documents stored-thread reading through its [app-server API](https://learn.chatgpt.com/docs/app-server). Agent Trace currently parses local files instead. The [source comparison](docs/mechanism.md#codex-source-and-supported-api) explains the distinction and format limitations.

## Structured attachment example

The normalized JSON above is the small runnable example's output. The [structured attachment exhibit](examples/production-structured-clip.json) is different: it was generated by the actual app's `parseAgentTrace` and `buildAttachmentClip` functions from our synthetic detailed text.

Start at `source_segments` for the exact input, then `reader_index`, `command_ledger` and `source_segment_index` for navigation. The source appears once; indexes refer to it. A test reconstructs the input byte for byte. [Provenance](docs/structured-clip-provenance.json) records the invocation and source hashes, and the [source excerpt](docs/structured-clip-source-excerpt.txt) shows the builder's relevant decisions.

The complete JavaScript builder is not bundled. This is an output exhibit from it, not another installed runtime. The 388-byte fixture produces about 18 KB of compact JSON because the fixed contract and indexes dominate this tiny example; it is not a compression demonstration.

## Code map and provenance

| File | Responsibility |
|---|---|
| [parser.py](src/trace_mechanism/parser.py) | Actual provider parsers, data classes and required helpers copied from Agent Trace. |
| [views.py](src/trace_mechanism/views.py) | Adapted compact, detailed and JSON projections. |
| [agent_tools.py](src/trace_mechanism/agent_tools.py) | Adapted search, exact source selection and stable paged snapshots. |
| [agent_demo.py](src/trace_mechanism/agent_demo.py) | Both directions of context retrieval using synthetic files. |
| [replay.py](src/trace_mechanism/replay.py) | Synthetic pending-to-completed record sequences. |
| [tests](tests/test_mechanism.py) | Provider examples, omissions, call/result pairing, snapshot stability and source hashes. |
| [provenance.json](docs/provenance.json) | Source and copied-symbol hashes; extraction and adaptation boundaries. |
| [controlled-run](examples/controlled-run/) | Selected real parent/child records, production-rendered views and structured attachment, with provenance. |

The parsers matched the original app's parsed objects on both synthetic fixtures. That establishes equivalence for those cases, not compatibility with every provider version. They selectively interpret records, skip malformed JSON, and cannot restore output omitted or truncated upstream. Newer paginated or compressed storage can need a different reader.

## Development and license

Propose changes as a patch with a synthetic regression case. Do not put real conversation logs in issues, tests or examples. See the [security reporting guidance](SECURITY.md). The layout check's attribution is in [tools/NOTICE.md](tools/NOTICE.md).

[Apache-2.0](LICENSE). This is an independent tool, not an OpenAI or Anthropic product.
