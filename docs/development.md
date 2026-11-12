# Development

[Usage](mcp.md) · [How it works](mechanism.md) · [README](../README.md)

## Source map

The MCP server loads an explicit manifest, then passes requests to the retrieval adapter. The adapter uses the native Codex reader or the conversation parsers according to the source format. None of these modules depends on the desktop app.

| Source | Responsibility |
|---|---|
| [codex_native.py](../src/trace_mechanism/codex_native.py) | Read events, normalize items, render views, search fields and compare states |
| [recordings.py](../src/trace_mechanism/recordings.py) | Identify physical recordings and verify selected file versions |
| [agent_tools.py](../src/trace_mechanism/agent_tools.py) | Select sessions and children, save captures and serve pages |
| [mcp_server.py](../src/trace_mechanism/mcp_server.py) | Load the manifest, define tools and run stdio transport |

The rest of the repository supports those files or the older text-processing path:

| Location | Contents |
|---|---|
| [skills/](../skills/agent-trace/SKILL.md) | Portable setup and retrieval instructions, copied by `tools/install_skill.py` |
| [tests/](../tests/) | Compatibility, identity, availability, paging and transport checks |
| [tools/](../tools/) | Run checks, capture MCP responses and regenerate examples |
| [examples/](../examples/README.md) | Current recordings, generated outputs and earlier compatibility records |
| [docs/](./) | Usage, implementation details, source provenance and [screenshots and diagram](images/) |
| [parser.py](../src/trace_mechanism/parser.py), [views.py](../src/trace_mechanism/views.py) | Claude Code and older Codex transcript formats and their views |
| [structurer.mjs](../src/trace_mechanism/structurer.mjs) | A separate index builder for rendered trace text |

## Run checks

Python 3.10+ runs the reader and server; Node.js 22+ runs the text index builder.
Run these commands from the repository root after cloning it.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp,test]'
.venv/bin/python -m pytest tests -q
.venv/bin/python tools/record_native_contract.py --check
.venv/bin/python tools/inspect_recorded_run.py
.venv/bin/python tools/inspect_agent_tree.py
.venv/bin/python tools/inspect_cross_provider.py
.venv/bin/python tools/demo_codex.py
node --test tests/structurer.test.mjs
.venv/bin/python tools/regenerate_examples.py --check
.venv/bin/python tools/check_layout.py
```

`record_native_contract.py` searches an actual recorded command and retrieves its output through a separate MCP server process. `--show` prints the retrieved evidence. Without `--check`, it updates [the saved responses](../examples/native-command-response.json). `demo_codex.py` checks the legacy transcript path. Neither executes commands from a recording.

`inspect_recorded_run.py` checks five commands from [a real validation investigation](investigation.md). The selected records and their provenance are in `examples/validation-history*`. `measure_retrieval.py` measures fresh and retained reads of a local history against literal search; [recorded measurements](../examples/retrieval-costs.json) are observations, not CI thresholds.

`inspect_agent_tree.py` retrieves a coordinator and two workers from [a fresh public-code review](agent-tree.md), retained in `examples/launch-review/`. `trace_mechanism.setup` owns local metadata listing, compatibility checks, explicit manifest creation, absolute connection settings and the local stdio verification command.

`inspect_cross_provider.py` reads [Claude's review of the Codex findings](cross-provider.md) and repeats its item reads. The selected records are in `examples/cross-provider/`. `NOTICE` retains Will Cook's attribution; `CITATION.cff` supplies citation metadata.

The editable [history-flow diagram](images/history-flow.svg) describes file selection and MCP requests. [Compact versus detailed](images/compact-detailed.svg) shows selected fields from the final command in `examples/validation-history.jsonl`; it abbreviates command paths and omits some output lines. Their SVG comments record the source, omissions and diagram-template licence.

When changing a tool, update [its reference](mcp.md) and test its actual stdio call, including the next operation that consumes the returned handle. These checks cover specific records and behavior; they are not retrieval-quality or performance benchmarks.

## Check the distributable package

```sh
.venv/bin/python -m pip install '.[mcp,test,build]'
.venv/bin/python tools/check_distribution.py
```

This builds a source distribution and a wheel from it, checks the package files
and licence notices, and installs the wheel into a temporary environment outside
the checkout. It then checks the installed JavaScript resource and Python entry
points and runs the real MCP search-and-read contract through stdio. It also
copies the workbench tests and their public fixtures outside the checkout and
runs them against that installed wheel with an isolated Python import path.
These checks cover a fresh home, launch from another directory, default and
custom history locations, `~` paths, spaces and Unicode, archived chats, both
providers, restarts, exact recording selection, preview copying and source
updates. The console entry point is started as a separate process; native copy
callbacks are simulated without writing the tester's system clipboard. It needs
network access to install build and runtime dependencies. It does not publish a
package or register a server with your apps.

## Provenance and compatibility records

The native reader and JavaScript builder are copied from the desktop app. [Reader provenance](provenance.json) and [builder provenance](structurer-provenance.json) identify their versions and bytes. Public checks verify those bytes and behavior; the relationship to private source is a maintainer declaration.

The [earlier retrieval recording](codex-retrieval.md), [controlled run](controlled-run.md), [production MCP excerpt](mcp-source-excerpt.txt) and [desktop skill excerpt](skill-source-excerpt.txt) document earlier versions. They support compatibility checks, not current setup. `regenerate_examples.py` owns their generated projections and indexes.

[The layout policy](repository_layout.json) defines directory responsibilities and the required public paths. Keep those paths stable when reorganizing files.

[Workbench sources and build](workbench.md): `src/trace_mechanism/workbench/` owns the frontend, local transport, library adapter and editable shelf. `tools/build_macos_app.py` packages the native window.
