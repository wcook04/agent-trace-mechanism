# Mechanism and boundaries

A provider writes local records. The parser groups them into turns and pairs calls/results by their recorded IDs. A view selects compact context or recorded detail. MCP makes search, read and paging available to a connected agent. Each read reopens the selected file; a hash identifies the returned text so later pages cannot silently switch to a newer version.

## Executable path

The public server requires an explicit file manifest; it does not scan a home directory. [MCP setup](mcp.md) shows how to connect it to a host. It exposes `search_trace_threads`, `read_chat_context` and `read_trace_page` over real stdio transport. Its snapshots are held in memory until server exit. The manifest is trusted configuration, and configured file contents become available to the connected client.

`full_thread_concise` means compact. `full_thread` means detailed. Both cover the selected file’s parsed turns, not independently verified original-session completeness. Compact retains prompts, visible messages, named calls and allowlisted command/path fields. Detailed retains arguments and results. Distinct source records remain in order; events inside one provider record do not acquire a fabricated order. JSON-string bodies are opaque text, so a quoted `TOOL` or `ASSISTANT` line is not another action.

`turn_ended` records a terminal boundary. `tool_evidence_complete` says whether observed calls/results have counterparts. `complete` requires both; it does not promise the provider file contains every event. A result with no initiating call has `missing_call`, not `missing_result`. A later prompt cannot supply an absent result. Codex app delivery envelopes are recognized narrowly as request inputs, with original record/thread provenance.

The JavaScript builder creates an optional JSON index with pointers into the exact supplied text. It does not prove that interpreted actions happened, establish original-session completeness, or compress every input. See [reproduction and semantic tests](development.md).

## Full app, plugin and skill

The desktop app adds session discovery, watchers, copy/export controls, richer native views and linked-child handling. Its plugin registers a local MCP server. Its retrieval skill tells an agent when to search, select an exact provider/session ID, start compact and ask for detail. The skill does not itself grant access. An agent can call tools directly without somebody opening the panel or copying text.

[Native MCP excerpt](mcp-source-excerpt.txt) and [retrieval skill excerpt](skill-source-excerpt.txt) document that integration. The full app also supports latest-response and last-N-turn scopes. Those are outside this public adapter. The Codex demonstration uses the installed plugin; the runnable replay uses this repository’s adapter.


## Existing Codex history access

Agent Trace’s added mechanism is search, consistent selection, evidence pairing, stable pages and reuse through agent tools.

At the inspected [public Codex revision](https://github.com/openai/codex/commit/43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c), the [record types](https://github.com/openai/codex/blob/43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c/codex-rs/history/src/rollout_payload.rs) and [writer](https://github.com/openai/codex/blob/43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c/codex-rs/rollout/src/recorder.rs) describe timestamped JSONL. That does not make the files a future-stable API.

The documented [app-server protocol](https://learn.chatgpt.com/docs/app-server) has history-reading methods. Installed versions and storage determine what is available. That is why the integration question is whether a reader should use that interface. No Codex implementation is vendored here.
