# Codex and Claude reading each other's work

During release preparation, Claude Code used this MCP server to inspect a real Codex review and its two workers. Codex then read Claude's session through the installed Agent Trace plugin.

The first Claude run found a real integration defect: its client showed `structuredContent`, while the server put retrieved text only in `content`. The adapter now supplies the same bounded page in both representations. On the second run, Claude could quote the workers' findings, retrieve a command-output page and check the fixes against the source. Codex read that response back and completed the documentation changes.

```sh
.venv/bin/python tools/inspect_cross_provider.py
```

This reads Claude's compact and detailed conversation, then repeats its three Codex item reads through the current server. It checks the two worker answers and the command-output page against what Claude actually received. It requires no model subscription and does not run the historical commands.

[Selected Claude records](../examples/cross-provider/claude-review.jsonl) · [Manifest](../examples/cross-provider/manifest.json) · [Selection provenance](../examples/cross-provider/provenance.json)

The sample retains the successful review turn's prompt, five MCP calls and results, visible progress and final answer. Other turns, file reads, thinking and host metadata are omitted. These are selected records, not a raw session export. The final answer predates the matching documentation fixes; it is evidence of the review, not the current issue list.

Both hosts can read either provider's conversations. Codex histories additionally support native item search, field retrieval, worker traversal and change queries. [Connect either host to your own selected files →](mcp.md#setup)
