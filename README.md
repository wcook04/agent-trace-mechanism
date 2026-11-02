# Agent Trace: parser mechanism

A small, local extraction of the parsers used by Agent Trace. Given one explicitly named Codex or Claude Code JSONL transcript, it groups captured prompts, assistant messages, tool calls and recorded results into turns. The examples are synthetic.

## First 60 seconds

Read [`examples/codex.jsonl`](examples/codex.jsonl), then its [expected output](examples/codex.expected.json). The second call has no recorded result; the parser marks the turn incomplete. [`examples/claude.jsonl`](examples/claude.jsonl) and its [output](examples/claude.expected.json) show the other format. The actual source-derived parser is [`src/trace_mechanism/parser.py`](src/trace_mechanism/parser.py).

Requires Python 3.10 or newer. From this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m trace_mechanism codex examples/codex.jsonl
.venv/bin/python -m trace_mechanism claude examples/claude.jsonl
.venv/bin/python -m unittest discover -s tests -v
python3 tools/check_layout.py
```

The parser uses only the Python standard library; installation uses setuptools. Running the parser requires no network access, account, provider SDK, application install or home-directory discovery; pip may download its build dependency during installation. It reads only the file supplied by the caller. The output may contain whatever sensitive information is in that file: **this extraction does not redact secrets**. Use synthetic inputs unless you intend to expose the output to whoever receives it.

## Boundary and provenance

The two parsers and their dependency functions are copied unchanged from Agent Trace's `cli_prompt_trace.py`, along with two required constants. [`docs/provenance.json`](docs/provenance.json) records SHA-256 hashes for the source file and each copied symbol. The CLI is a new, deliberately small projection of the parsed objects; it does not expose every field. Tests compare each copied block with its recorded source hash and run both synthetic examples against checked-in expected output. Hashes establish correspondence to the recorded extraction, not independent authenticity of the source.

This is **not** the full Agent Trace app or plugin. It omits discovery, indexing, SQLite, live refresh, UI, MCP, snapshots, redaction and sharing. The source parsers skip malformed JSON lines and represent captured records only; they do not reconstruct missing events or server-hidden reasoning. The example includes a saved compaction record to illustrate an input type; this narrow CLI does not extract it. The Codex fixture exercises `event_msg` task lifecycle and `response_item` function calls and outputs; the Claude fixture exercises user messages, assistant `tool_use` and user `tool_result` blocks. Parsing is selective, not a lossless transcript reader: it does not guarantee support for every newer or paginated rollout shape, and provider-side output may already be truncated. Formats may change, and these examples are not exhaustive compatibility tests.

`src/` owns parsing and the CLI, `examples/` holds synthetic cases, `tests/` verifies behavior and provenance, `docs/` records provenance and layout, and `tools/` holds the portable layout check. The latter is copied from the repository-organization skill; see [`tools/NOTICE.md`](tools/NOTICE.md).

## License

Apache-2.0, a draft choice for this local review copy. Review rights and licensing before any release. Contributions can be proposed as a patch with a synthetic regression case.
