# Documentation

## Using Agent Trace

- [Use Agent Trace from an agent](mcp.md): install it and call it from Claude Code or Codex.
- [Agent Trace Structurer](workbench.md): the desktop app for choosing what to copy.
- [How it works](mechanism.md): how saved conversations are read and what the compact and detailed views keep.
- [Development](development.md): tests, checks and how the examples are regenerated.

## Studies

Write-ups of specific runs, each with its files under [`examples/`](../examples/README.md).

- [Telling a second model what a copied conversation leaves out](studies/reviewer-visibility.md), with its [full record](studies/reviewer-visibility-full-record.md).
- [Codex and Claude reading each other's work](studies/cross-provider.md)
- [A real review with two subagents](studies/agent-tree.md)
- [Checking a worker's validation history](studies/investigation.md)
- [Earlier context-retrieval recording](studies/codex-retrieval.md)
- [Historical controlled Codex run](studies/controlled-run.md)

## Records

These files are read by the tests and are cited inside the recorded examples, so they stay at this level.

- `provenance.json`, `structurer-provenance.json`, `structured-clip-provenance.json`: where each copied source file came from, with hashes.
- `mcp-source-excerpt.txt`, `skill-source-excerpt.txt`, `structured-clip-source-excerpt.txt`: excerpts of the private source that the public code was taken from.
- `repository_layout.json`: the folder roles that `tools/check_layout.py` enforces.
- `images/`: screenshots and diagrams used by the pages above.
