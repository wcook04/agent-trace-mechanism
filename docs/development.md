# Reproduce and check

Python 3.10+ runs the provider parsers. Install `.[mcp]` in a virtual environment for the real stdio adapter and tests. Node.js 22+ runs the standalone JavaScript builder and its tests. No model account or private repository is needed.

```sh
.venv/bin/python tools/demo_codex.py
.venv/bin/python -m unittest discover -s tests -v
node --test tests/structurer.test.mjs
.venv/bin/python tools/regenerate_examples.py --check
.venv/bin/python tools/check_layout.py
```

To refresh generated files after a source change, run `tools/regenerate_examples.py` without `--check`. This owns synthetic provider views, selected Codex views, the small index exhibit, the Codex result index, the historical native-text index and their output provenance. CI checks reproduction.

## Inspect the index

```sh
node tools/build_index.mjs examples/codex-retrieval/after.detailed.txt /tmp/trace-index.json --single
.venv/bin/python -c 'import json; x=json.load(open("/tmp/trace-index.json")); print(x["terminal_state_index"]["final_assistant_message"]["body"])'
```

This returns the corrected 10:30/£21 answer, with its source line range available beside `body`. For the small edit fixture, `artifact_delta_index.rows` separates the recorded read from the successful patch. `command_ledger` and `validation_matrix` point to detected commands/results. Unknown wrappers remain unknown; arbitrary JavaScript is never evaluated to infer execution.

The index is optional and can be larger than its source. Small examples use a self-contained JSON file. Larger inputs can produce an index plus a named raw sidecar. The sidecar carries the exact supplied text, with UTF-8 byte ranges in the index. Original-session coverage remains unknown. Use ordinary compact retrieval when an index adds nothing to the question.

## Source and tests

[Parser provenance](provenance.json) hashes each copied source symbol. [Builder provenance](structurer-provenance.json) pins the complete, byte-identical JavaScript file and identifies the test import adaptation. Both are Will Cook’s code under this repository’s Apache-2.0 licence. The Python views, registry and MCP adapter are inspection implementations.

Tests distinguish source preservation from interpretation: missing calls/results and empty results; terminal versus evidence completeness; chronological records; opaque quoted roles; real MCP initialization/search/read/refresh/paging; instructions versus edits/commits; successful and failed patches; bounded executed checks versus mentioned checks; coverage uncertainty; graph semantics; correct carrier filenames; reconstruction and source hashes. These cases do not establish compatibility with every provider release.

The [layout policy](repository_layout.json) assigns runtime to `src`, tests to `tests`, commands to `tools`, selected/synthetic data to `examples`, and explanations/provenance to `docs`. The [review record](review-fixes.md) maps the supplied review to changes and remaining evidence limits.
