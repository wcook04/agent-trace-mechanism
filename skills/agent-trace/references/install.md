# Install Agent Trace on this machine

Agent Trace is a local Python package and stdio MCP server. It reads selected
Codex and Claude Code session files. No API key is needed for the reader or its
checks; using an AI host is separate. Install it on the machine where the host
launches MCP and can read the histories. A cloud agent cannot see a laptop's files
just because the same account is signed in.

## Establish the paths

Use Git and Python 3.10 or newer. Choose a persistent checkout directory; don't
assume a username, home path or current working directory. Clone
`https://github.com/wcook04/agent-trace-mechanism.git` there if it isn't already
available. Inspect an existing checkout before reusing it; don't overwrite it.

From that checkout, on macOS, Linux or WSL:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[mcp]'
TRACE_PYTHON="$PWD/.venv/bin/python"
TRACE_MANIFEST="$PWD/agent-trace.local.json"
```

On Windows PowerShell:

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install '.[mcp]'
$TracePython = (Join-Path (Get-Location).Path '.venv\Scripts\python.exe')
$TraceManifest = (Join-Path (Get-Location).Path 'agent-trace.local.json')
```

Use the Python executable in the virtual environment directly; activation is
unnecessary. If `py` is unavailable, use the installed Python 3.10+ executable.
Do not resolve the venv executable's symlink to a base Python installation.
Quote paths containing spaces. WSL and Windows are distinct environments: keep
the host, interpreter and readable history paths in the same environment.

In the commands below, `"$TRACE_PYTHON"` means that absolute interpreter path.
In PowerShell use `& $TracePython` instead, and `$TraceManifest` for the manifest.
No runtime step depends on the shell still being in the checkout.

## Select histories

```sh
"$TRACE_PYTHON" -m trace_mechanism.setup list --provider codex
"$TRACE_PYTHON" -m trace_mechanism.setup list --provider claude
```

These list metadata, not conversation text, and register nothing. Codex searches
both `sessions` and `archived_sessions` under `$CODEX_HOME` or `~/.codex`; Claude defaults to
`$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`. Variables are read from the
setup process's environment. Use `list --provider codex --root "/actual/history/folder"`
to search only that directory instead. If a root
is absent, find the host's actual configuration or make a local chat first;
don't recursively search the entire disk.

Check only files the user intends to make available:

```sh
"$TRACE_PYTHON" -m trace_mechanism.setup check "/actual/history/file.jsonl"
"$TRACE_PYTHON" -m trace_mechanism.setup register "/actual/history/file.jsonl" --manifest "$TRACE_MANIFEST"
```

Replace the example path with a listed file. `check` reports `native`,
`legacy_conversation`, `conversation` or `unsupported`; inspect diagnostics.
Native item queries require native Codex records. Claude histories support
conversation views. Neither a new producer version nor a zero-match search alone
proves incompatibility.

Pass multiple selected paths to `register` for both providers or a Codex parent
and its workers. It writes absolute paths and only links selected recorded
parents/children. It refuses to overwrite an existing manifest. For an existing
installation, inspect and update that manifest while retaining its selected
entries, or create a differently named manifest; don't discard another selection.

A registered file's supported contents become available, including old private
outputs. The host may send retrieved text to its model provider. There is no
automatic redaction. Keep the manifest local and out of version control.

## Verify and connect

```sh
"$TRACE_PYTHON" -m trace_mechanism.setup verify --manifest "$TRACE_MANIFEST"
"$TRACE_PYTHON" -m trace_mechanism.setup connection --manifest "$TRACE_MANIFEST"
```

`verify` starts a temporary local MCP process, checks listing and reads each
selected chat without printing its transcript. It calls no model. `connection`
prints the absolute `command` and `args` for a host's stdio configuration.
It doesn't change host settings. A successful local check does not establish
that a host has loaded the server.

Check for an existing `agent-trace` connection with the host's `mcp get` command
before adding one. Preserve unrelated settings. With the relevant CLI installed,
choose one or both hosts:

```sh
codex mcp add agent-trace -- "$TRACE_PYTHON" -m trace_mechanism.mcp_server --manifest "$TRACE_MANIFEST"
codex mcp get agent-trace

claude mcp add --scope user --transport stdio agent-trace -- "$TRACE_PYTHON" -m trace_mechanism.mcp_server --manifest "$TRACE_MANIFEST"
claude mcp get agent-trace
```

In PowerShell substitute `$TracePython` and `$TraceManifest` for the shell
variables above. If a CLI is absent, use the host's local stdio MCP settings and
the values printed by `connection`; don't use relative paths or guess a remote
server URL. If the host only supports remote HTTP MCP, this stdio package does
not connect directly. Managed host policies can also restrict local MCP.

Claude's `--scope user` makes the connection available across projects. For one
project, run its add command from that project with `--scope local`, retaining
the absolute interpreter and manifest paths. Skill scope and MCP scope are
separate; copying a skill into a project does not narrow a user-scoped server.

Restart the host or open a new chat in the user's working project. Ask it to call
`search_trace_threads`, then `read_chat_context` for one registered session.
Check the returned session identity and actual text, not just the connection
label. For a native Codex file, also search a command and retrieve its output.
If the tools are absent, inspect the host's MCP status/logs and configured paths.
Don't claim success or weaken sandbox/permission settings to hide a failure.

## Install the optional skill

From the source checkout, using its Python interpreter:

```sh
python3 tools/install_skill.py --host codex --dry-run
python3 tools/install_skill.py --host codex
python3 tools/install_skill.py --host claude
```

On Windows use `py -3` or the environment's Python. The installer copies the
complete skill and its references. It registers no histories and changes no MCP
settings. It refuses to replace an existing skill, including a symlink.

Codex uses `~/.agents/skills/agent-trace`; Claude uses
`~/.claude/skills/agent-trace` (or the configured Claude directory). For one
project, add `--scope project --project "/actual/project"`. This targets
`.agents/skills` or `.claude/skills` in that project, not whichever directory
happens to be current. `--skills-dir "/custom/skills"` overrides the destination
when a host uses a different skill location. Restart the host and check that
`agent-trace` appears in its skill selector; invoke `$agent-trace` in Codex or
`/agent-trace` in Claude. Copying files alone is not a host-discovery test.

## Update, relocate or remove

Keep the checkout and its venv at their configured paths. After updating the
checkout, reinstall `.[mcp]` with that interpreter, rerun `verify`, then restart
the host. Review changes before replacing an installed skill. Its copied files
do not update automatically.

If you move the checkout, recreate the venv at its new location and update the
host's command and manifest arguments. Venvs are not portable directory bundles.
Session paths in a manifest must also be updated if the histories move.

Disconnect with `codex mcp remove agent-trace` or
`claude mcp remove --scope user agent-trace`. For Claude local scope use
`--scope local` from that project. Stop the connected host/server to clear its
retained captures; removing configuration alone doesn't erase a running process's
memory or anything already received by the host. Remove only the installed
`agent-trace` skill directory if it is no longer wanted. Original histories are
not modified.

Host references: [Codex skills](https://developers.openai.com/codex/skills/),
[Claude skills](https://code.claude.com/docs/en/skills),
[Claude environment variables](https://code.claude.com/docs/en/env-vars),
[Claude MCP scopes](https://code.claude.com/docs/en/mcp#user-scope).
