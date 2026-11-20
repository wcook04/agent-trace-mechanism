# Documentation

## Using Agent Trace

- [Use Agent Trace from an agent](mcp.md): install it and call it from Claude Code or Codex.
- [Agent Trace Structurer](workbench.md): the desktop app for choosing what to copy.
- [How it works](mechanism.md): how saved conversations are read and what the compact and detailed views keep.
- [Development](development.md): tests, checks and how the examples are regenerated.

## Studies

Write-ups of specific runs, each with its files under [`examples/`](../examples/README.md).

- [Reading a worker's saved run in another chat](studies/capture-review.md), with a [capture you can read yourself](../examples/portable-capture/README.md).
- [Telling a second model what a copied conversation leaves out](studies/reviewer-visibility.md), with its [full record](studies/reviewer-visibility-full-record.md).
- [Codex and Claude reading each other's work](studies/cross-provider.md)
- [A real review with two subagents](studies/agent-tree.md)
- [Checking a worker's validation history](studies/investigation.md)
- [Earlier context-retrieval recording](studies/codex-retrieval.md)
- [Historical controlled Codex run](studies/controlled-run.md)

## Records

- [`records/`](records/): where each copied source file came from, with hashes (`provenance.json`, `structurer-provenance.json`, `structured-clip-provenance.json`), and excerpts of the private source that the public code was taken from (the three `*-source-excerpt.txt` files). The tests read these. Some older recordings under `examples/` name them by their earlier path, `docs/<file>`.
- [`repository_layout.json`](repository_layout.json): the folder roles that `tools/check_layout.py` enforces.
- [`images/`](images/): screenshots and diagrams used by the pages above.
