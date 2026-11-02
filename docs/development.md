# Development

Python 3.10+ runs the record reader and MCP server. Node.js 22+ runs the separate structured-text index builder.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp,test]'
.venv/bin/python -m pytest tests -q
.venv/bin/python tools/record_native_contract.py --check
.venv/bin/python tools/demo_codex.py
node --test tests/structurer.test.mjs
.venv/bin/python tools/regenerate_examples.py --check
.venv/bin/python tools/check_layout.py
```

The first MCP command searches an actual recorded development command and retrieves its output through a separate stdio server process. It checks the responses against [the published capture](../examples/native-command-response.json). To intentionally update that capture, run it without `--check` and inspect the changes. `demo_codex.py` exercises the retained legacy transcript path. Neither command executes tools from a recording.

## Source map

| Source | Role |
|---|---|
| `src/trace_mechanism/codex_native.py` | Shared record reader: native events, normalization, views, item search, field retrieval and state comparison |
| `src/trace_mechanism/agent_tools.py` | Public adapter: explicit session selection, child traversal, captures and paging |
| `src/trace_mechanism/mcp_server.py` | Manifest loading, tool schemas and transport |
| `src/trace_mechanism/parser.py`, `views.py` | Older transcript formats and their views |
| `src/trace_mechanism/structurer.mjs` | Separate index over supplied rendered trace text; not needed by the native MCP path |
| `tests/` | Record compatibility, identity, status, availability, paging, tool composition, stdio transport and legacy regressions |

The core and JavaScript builder are copied from the desktop application. [Core provenance](provenance.json) and [builder provenance](structurer-provenance.json) identify the copied bytes. Public checks can verify those bytes and their behavior; their relationship to the private application source is a maintainer declaration, not something a public hash alone independently proves.

`tools/regenerate_examples.py` owns the retained legacy projections and indexes. The [earlier retrieval recording](codex-retrieval.md), [controlled run](controlled-run.md), [production MCP excerpt](mcp-source-excerpt.txt) and [desktop skill excerpt](skill-source-excerpt.txt) are historical reference material. They are not setup instructions for the current public server. Its supported operations are in [the MCP guide](mcp.md).

Tests and recorded responses establish the listed behavior on their covered inputs. They do not measure retrieval quality or context savings against other history tools, and they do not establish compatibility with every Codex release or fork layout.

The [layout policy](repository_layout.json) places runtime code in `src`, tests in `tests`, maintenance commands in `tools`, records in `examples`, and explanations in `docs`. When changing a public tool, update its guide and exercise its actual stdio call, including any next operation that consumes its returned handle.
