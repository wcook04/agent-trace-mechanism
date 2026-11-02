# Development

Python 3.10+ runs the native record engine and MCP adapter. Node.js 22+ runs the structured index builder.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp,test]'
.venv/bin/python -m pytest tests -q
node --test tests/structurer.test.mjs
.venv/bin/python tools/regenerate_examples.py --check
.venv/bin/python tools/check_layout.py
```

## Source map

- `src/trace_mechanism/codex_native.py`: portable production native-item engine; byte identity recorded in [provenance](provenance.json).
- `src/trace_mechanism/structurer.mjs`: complete production index builder; [provenance](structurer-provenance.json).
- `src/trace_mechanism/agent_tools.py` and `mcp_server.py`: smaller explicit-file public adapter.
- `src/trace_mechanism/parser.py` and `views.py`: legacy record support.
- `tests/`: native identity, typed status, duplicate handling, field paging, deltas, exact child links and real stdio MCP transport, plus legacy regressions.

The native core is shared with the desktop app. Its tests check malformed/partial records, SQLite read-only access, source identity, repeated lifecycle events, preserved originals and immutable reads. The builder tests check typed action/status interpretation and exact source reconstruction. Unit-test records are test inputs, not a product demonstration.

`tools/regenerate_examples.py` owns the retained legacy regression projections and their provenance. Run it without `--check` after changing the copied builder. Those historical fixtures are kept to catch compatibility regressions.

The [layout policy](repository_layout.json) keeps runtime in `src`, tests in `tests`, maintenance commands in `tools`, and reference material in `docs`.
