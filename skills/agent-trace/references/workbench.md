# Install the workbench or maintain its prompt shelf

For the pictured **Agent Trace Structurer** window, use the public checkout of
`wcook04/agent-trace-mechanism`. No private plugin, account, Node installation,
MCP connection, or second provider is required. Keep the user's existing app,
skills, prompts, and provider settings intact.

On macOS, a built `Agent Trace Structurer.app` includes its Python runtime.
Open that app if the user already has it. To build it from the public source
with Python 3.10+:

```sh
# Start in the supplied candidate Git checkout containing tools/build_macos_app.py.
python3 -m venv .venv
.venv/bin/python -m pip install '.[desktop,mac-build]'
.venv/bin/python tools/build_macos_app.py
open 'dist/Agent Trace Structurer.app'
```

The build is for the local Mac architecture; it is ad-hoc signed, not notarized.
Copy the **whole** app to a convenient folder. Check for an existing destination
before copying. The browser version needs only Python: install the checkout with
`python -m pip install .` in a venv, then run that venv's `agent-trace-app`.
On Windows use `.venv\Scripts\python.exe` and `.venv\Scripts\agent-trace-app.exe`.
On macOS `agent-trace-app --desktop` also opens the native window when the
desktop extra is installed. Stop browser mode with Ctrl+C.

Start the user's chosen provider and make a chat if the list is empty. Agent
Trace reads Codex from `$CODEX_HOME/sessions` or `~/.codex/sessions`, Claude
Code from `$CLAUDE_CONFIG_DIR/projects` or `~/.claude/projects`. Test a listed
session with the requested scope and copy action. The app never registers these
files with MCP. Use the separate setup guide only when agent access is wanted.

**Add or edit a prompt.** In the app, open **Manage prompts**, select New prompt
or an existing prompt, edit the Markdown, and save. Click its shelf button to
copy the body. An agent can do the same job on disk:

1. Read the directory shown in Manage prompts or printed by `agent-trace-app
   --prompts-dir`; by default it is `~/.agent-trace/prompts`. A launch may
   override it with `AGENT_TRACE_PROMPTS`.
2. Inspect existing files. Use a short unique name such as `review-tests.md`
   (letters, digits, dashes, underscores). Put the user's wording in the body.
   For a shorter button label, optional front matter supports `title:` and
   `cockpit_slot:`. Editing a bundled starter creates a user override.
3. Create a new file without overwriting an existing prompt. For requested edits
   read the current file first and preserve unrelated metadata. Never write
   inside the app bundle. Press **Refresh** on the shelf and verify the title
   and body using **Preview prompt text**. Removing a user override makes the bundled starter visible again.
