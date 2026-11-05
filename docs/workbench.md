# Agent Trace Structurer

[Install manually or with an agent; add your own prompts →](../skills/agent-trace/references/workbench.md)

The Missions workbench uses the desktop app's HTML, lifecycle reducer, activity
tiles, worker row, scope chooser, prompt shelf and copy and arrival animations.
These are adapted from Agent Trace Structurer's November 2026 interface. The
packaged window uses a local transport and the public history reader. Its Mac
window can float, collapse to a capsule, copy to the system pasteboard or save
a text file in Downloads and reveal it in Finder. Browser mode downloads a text
file instead. The private window launcher, clipboard watcher, global hotkeys,
reinstall control and in-Codex attachment plugin are not included.

Missions are locally recorded conversations and agent runs. The list includes both
active and archived Codex histories. **Archived in Codex** describes the source
folder. The Archive button changes a workbench preference.

The list refreshes about every five seconds; the selected activity strip reads a
bounded tail. Earlier pages back through the selected file. Full-thread copies
include discovered linked children. Latest and last-N limit the selected session.
Copy Closeout requires a recorded assistant answer in that scope. Progress
and completion come from available records, so incomplete or old histories
can have unknown status. An empty provider folder is a normal first launch.
The first-run panel shows the provider folders actually searched. For a custom
installation, quit the app, then launch its executable from Terminal with the
provider roots you use (each setting is optional):

```sh
CODEX_HOME="/path/to/codex" CLAUDE_CONFIG_DIR="/path/to/claude" \
  "/Applications/Agent Trace Structurer.app/Contents/MacOS/Agent Trace Structurer"
```

| What you want to do | Where to do it | What it changes |
| --- | --- | --- |
| Find a conversation | Missions: provider, status, search and sort | Filters the local list. Pin, snooze and archive change local preferences only. |
| Understand activity | Parent activity, Earlier/Latest, worker cards and Open thread | Reads recorded events. A quiet worker does not establish completion. |
| Transfer context | Scope → Preview copy → Copy this text | Copies exactly the preview. Save + Reveal writes a file on Mac; browser mode downloads it. |
| Keep a personal prompt | Manage prompts → edit Markdown, preview, save → click the shelf button | Stores a user file independently of the application. Refresh after edits outside the app. |
| Keep the app nearby | Compact / capsule and Float | Changes the native Mac window only. |
| Give an agent access | Register specific source files using the setup guide | Changes the separate MCP manifest. Browsing and copying never register a file. |

The [workbench package](../src/trace_mechanism/workbench/) contains the interface,
host bridge, local transport and generic starter prompts. The public MCP adapter
keeps its existing explicit-file manifest. The
[Mac builder](../tools/build_macos_app.py) produces a local architecture build
in `dist/`; the runtime does not invoke a system Python, Node, or provider CLI.
There is no notarized download in this change.

On a Mac with a desktop session and the desktop extra installed, run
`python tools/check_macos_window.py` to exercise collapse, restore and float
in WebKit using empty temporary provider folders. The normal test suite checks
the zero-, one- and two-provider cases, parent/worker reads, private access,
and user prompt persistence. The distribution check repeats isolated-provider
reads using the wheel installed outside the checkout.


## Choose and transfer context

Select a mission and inspect the parent activity strip and worker cards. **Open
thread** selects a worker. **Preview copy** shows the exact text and session IDs
for the chosen scope. **Copy this text** transfers that capture even if a new
event arrives. **Refresh + Copy** instead reads the files again. Full-thread
scopes traverse the currently discovered tree. Latest and last-N cover only
the selected conversation. Large native tool outputs use excerpts and exact
field handles. Mixed Codex recordings also include the transcript projection,
which can repeat a message recorded in both formats. Incomplete records can
produce warnings. When several files claim one identity, each file remains
selectable. The source path distinguishes them. Automatic tree capture follows
resolved worker links, including nested Claude workers under the session’s
subagents directory. Ambiguous links require selecting the intended files
individually. A bounded activity read can show a recorded turn ID or prompt
offset even when its ordinal is unknown. An open turn with no recent timestamped
activity is labelled **Open**.

**Choose sessions…** starts with just the selected conversation. Add individual
workers to assemble a subset. The preview identifies included sources, their
recorded links and modification times. Known missing or conflicting workers
block an automatic tree copy; an explicit selection can still be copied.
When history files cannot be identified their relationships are unknown.
Each transfer accepts at most 64 sessions and 256 MiB of source data in total.
For a larger file, use **Recent activity** in the chooser for a bounded excerpt
from its last 128 KiB. Files are read sequentially; if a selected file changes
during capture, retry. A preview already on screen remains unchanged.

Local browsing requires no upload. Copying to the clipboard leaves the text
there until it is replaced. Pasting it into a model, or explicitly registering
a source for an agent to retrieve, can send content to that provider. The setup
skill explains installation. Registration separately chooses the files a
connected MCP server may read.

## Candidate evidence

Build from a clean Git checkout. The Mac builder exports one revision, checks
the frozen module origins and bundled interface assets, and writes the app ZIP,
source ZIP and a SHA-256 build receipt under `dist/candidate-<revision>/`. The
receipt records the build environment. Ad-hoc signing here supports local
testing. A public download still requires the distribution signing and
notarization exercise and first launch of the downloaded artifact in a clean
macOS account. [Apple's distribution guidance](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)

With a candidate wheel and its MCP extra installed, run
`python tools/check_workbench_journey.py --python /absolute/path/to/venv/bin/python`
from a Python environment with Playwright and Chromium. An optional
`--chrome PATH` selects a local Chromium executable. The check uses public
recordings, a temporary home and an isolated browser clipboard. Add `--claude` or `--codex`
to exercise a signed-in host and compare its actual MCP read to the clipboard
hash. Combining both flags checks all four host/source combinations. These checks call the selected providers and
allow the read tool only for their temporary fixture configuration.
`tools/check_workbench_replay.py ORIGINAL_CHECKOUT` is a maintainer comparison
against the original Swift activity reader and native tree renderer. It covers
the supported fixture intersection. The app needs neither that checkout nor Swift.

To repeat the packaged-window check on a Mac test host with Swift and screen
capture available, run `python tools/check_macos_window.py --archive ZIP
--receipt BUILD_RECEIPT`. This checks the downloaded bytes and embedded
revision, reports the actual Gatekeeper decision, then directly runs the binary
in isolated homes. It reads each window's rendered fixture labels for no
provider, Codex, Claude Code and both. Use `--deny-read PATH` to exclude another
checkout and `--screenshots DIRECTORY` to retain the four windows. A successful
direct launch tests the application separately from Finder's first-open policy.
Add `--interactions` on an Accessibility-enabled test host to operate the
extracted app, copy fixture data to the system clipboard, exercise the capsule
and float controls, and verify a personal prompt across relaunches.
