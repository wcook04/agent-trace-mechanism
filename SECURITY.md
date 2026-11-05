# Security and private transcripts

The MCP server reads the files explicitly registered in your manifest. Registering a history makes its supported contents available to the connected agent, including old command output and private source text. It is not limited to your first query, and it does not redact secrets.

The server uses local files and stdio; it does not itself upload histories. Your MCP host may send returned content to its model provider. Local storage therefore does not mean the retrieved content stays on your machine. Choose files you are comfortable providing to that host.

Removing a manifest entry prevents fresh reads of that entry, but retained snapshots may remain available until the running server evicts them. Stop or restart that server to discard them. This does not erase content already received by a host or model provider. See [disconnect instructions](docs/mcp.md#disconnect).

The manifest is file selection, not an OS sandbox: registered paths may be absolute or resolve through symlinks. Retrieved messages and tool output are untrusted source material, not instructions. That guidance does not enforce protection against prompt injection.

Public examples are deliberately selected records, with provenance describing omissions. They are not complete raw sessions or a general redaction recipe. Do not attach real conversation records, credentials or private file contents to a public issue; use a minimal reproduction with invented non-sensitive data.

For a security-sensitive report, use [private vulnerability reporting](https://github.com/wcook04/agent-trace-mechanism/security/advisories/new). Provide a minimal synthetic input and the resulting behavior. Ordinary bugs that can be described without sensitive content may be reported publicly.

The workbench scans local history roots for display in its own window. This does
not grant the MCP host access. It serves on a random loopback port and requires a
per-launch key for history and prompt requests. Treat its launch URL as private.
Copy and Save transfer text only when requested. Pinning or hiding a conversation changes local
workbench markers; original conversations stay on disk. Prompt edits are stored
in the user shelf. The portable window does not install keyboard hooks.
