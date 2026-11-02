# How the review example relates to Agent Trace

## Data flow

1. A provider writes records to a local conversation file.
2. The provider parser groups prompts and subsequent events into turns.
3. Calls and results are paired by recorded call ID. Missing results remain missing.
4. A scope selects a compact or detailed projection.
5. An agent reads the result. Stable paged snapshots prevent background activity from changing a page halfway through retrieval. The current full MCP reader rejects rendered traces over 16 MB; that is a reader limit, not a claim that larger source files contain no useful information. Native exports have a different implementation.

The two parsers, three data classes and seven helpers in parser.py are copied source blocks, with hashes in provenance.json. The remaining runnable code is a small adaptation for inspection. Its renderers and registry are not byte-for-byte replacements for the full app.

## Plugin and skill

The full app's manifest registers a local stdio MCP server. Its installer can connect the same server to Claude Code and install the same retrieval skill. The host supplies tools to its agent; the skill explains when to use them. A skill does not itself grant filesystem access.

The production [MCP excerpt](mcp-source-excerpt.txt) shows the mapping:

| Tool scope | Meaning |
|---|---|
| `full_thread_concise` | Full thread compact |
| `full_thread` | Full thread detailed |
| `latest_prompt_cycle` | Latest response bundle |
| `last_n_turns:N` | Last N turns |

The runnable example implements the first two scopes. Search uses an explicit registry of synthetic files and matches title, provider and ID. The full plugin discovers local sessions and also searches the first-prompt preview. Its `claude_code` provider accepts `claude` as an alias; this example uses `claude`.

The native interface separately allows a person to preview, copy or save a thread. Agent tools do not require those steps. The full app's context attachment action inserts a resource for review in the composer; it does not automatically send a message.

## What is adapted

- **Views:** compact shows prompts, final assistant text, named calls and selected command/path keys. Detailed adds parsed arguments and outputs. Production also has chronological progress, provenance, linked children and indexing.
- **Live reading:** appended fixture records are reparsed on a new read. Native watchers, file-tail optimisation and roster refresh are omitted.
- **Agent boundary:** method names and scope concepts follow the app. Registry and snapshots are in-memory adaptations; MCP transport is not installed.
- **Structured output:** normalized turns and tool records are exposed directly. The full app's larger structured reader packets and indexes are not reproduced.
- **Redaction:** omitted here. This example must not be mistaken for a safe exporter of arbitrary private logs.

## Codex source and supported API

Inspected public revision: [43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c](https://github.com/openai/codex/commit/43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c).

The [record types](https://github.com/openai/codex/blob/43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c/codex-rs/history/src/rollout_payload.rs#L30-L74) describe tagged type/payload events. The [writer](https://github.com/openai/codex/blob/43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c/codex-rs/rollout/src/recorder.rs#L2075-L2108) serializes timestamped JSONL. This supports the format interpretation without making it a future-stable API.

The documented [app-server protocol](https://learn.chatgpt.com/docs/app-server) offers thread/list, thread/read, thread/turns/list and thread/items/list. Installed versions and the history store determine support. That API returns a history projection; direct parsing returns a different selected view.

The [persistence policy](https://github.com/openai/codex/blob/43ad1cbf3016e9944b3b5d0b0e127ce7148c9d7c/codex-rs/rollout/src/policy.rs) differs between legacy and paginated history, and some saved outputs are truncated. The example neither restores missing data nor proves every current event shape is covered. No Codex implementation is vendored here.
