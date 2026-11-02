# Development

[Usage](mcp.md) · [How it works](mechanism.md) · [README](../README.md)

## Source map

The current MCP retrieval path is three files:

| Source | Responsibility |
|---|---|
| [codex_native.py](../src/trace_mechanism/codex_native.py) | Read events, normalize items, render views, search fields and compare states |
| [agent_tools.py](../src/trace_mechanism/agent_tools.py) | Select sessions and children, save captures and serve pages |
| [mcp_server.py](../src/trace_mechanism/mcp_server.py) | Load the manifest, define tools and run stdio transport |

The rest of the repository supports those files or the older text-processing path:

| Location | Contents |
|---|---|
| [tests/](../tests/) | Compatibility, identity, availability, paging and transport checks |
| [tools/](../tools/) | Run checks, capture MCP responses and regenerate examples |
| [examples/](../examples/) | Selected source records and generated outputs |
| [docs/](./) | Usage, implementation details and source provenance |
| [parser.py](../src/trace_mechanism/parser.py), [views.py](../src/trace_mechanism/views.py) | Older transcript formats and their views |
| [structurer.mjs](../src/trace_mechanism/structurer.mjs) | A separate index builder for rendered trace text |

## Run checks

Python 3.10+ runs the reader and server; Node.js 22+ runs the text index builder.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp,test]'
.venv/bin/python -m pytest tests -q
.venv/bin/python tools/record_native_contract.py --check
.venv/bin/python tools/inspect_recorded_run.py
.venv/bin/python tools/demo_codex.py
node --test tests/structurer.test.mjs
.venv/bin/python tools/regenerate_examples.py --check
.venv/bin/python tools/check_layout.py
```

`record_native_contract.py` searches an actual recorded command and retrieves its output through a separate MCP server process. `--show` prints the retrieved evidence. Without `--check`, it updates [the saved responses](../examples/native-command-response.json). `demo_codex.py` checks the legacy transcript path. Neither executes commands from a recording.

`inspect_recorded_run.py` checks five commands from [a real validation investigation](investigation.md). The selected records and their provenance are in `examples/validation-history*`. `measure_retrieval.py` measures fresh and retained reads of a local history against literal search; [recorded measurements](../examples/retrieval-costs.json) are observations, not CI thresholds.

When changing a tool, update [its reference](mcp.md) and test its actual stdio call, including the next operation that consumes the returned handle. These checks cover specific records and behavior; they are not retrieval-quality or performance benchmarks.

## Provenance and compatibility records

The native reader and JavaScript builder are copied from the desktop app. [Reader provenance](provenance.json) and [builder provenance](structurer-provenance.json) identify their versions and bytes. Public checks verify those bytes and behavior; the relationship to private source is a maintainer declaration.

The [earlier retrieval recording](codex-retrieval.md), [controlled run](controlled-run.md), [production MCP excerpt](mcp-source-excerpt.txt) and [desktop skill excerpt](skill-source-excerpt.txt) document earlier versions. They support compatibility checks, not current setup. `regenerate_examples.py` owns their generated projections and indexes.

[The layout policy](repository_layout.json) defines directory responsibilities and the required public paths. Keep those paths stable when reorganizing files.
