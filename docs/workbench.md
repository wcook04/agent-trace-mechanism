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

The list refreshes about every five seconds; the selected activity strip reads a
bounded tail. Earlier pages back through the selected file. Full-thread copies
include discovered linked children. Latest and last-N limit the selected session.
Copy Closeout requires a recorded assistant answer in that scope. Progress
and completion come from available records, so incomplete or old histories
can have unknown status. An empty provider folder is a normal first launch.
Click Refresh after editing shelf files outside the app.

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
produce warnings. A duplicate session identity needs resolving on disk.

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
recordings, a temporary home and an isolated browser clipboard. Add `--claude`
to exercise a signed-in Claude Code session and compare its actual MCP result
to the clipboard hash. This optional step calls the provider.
`tools/check_workbench_replay.py ORIGINAL_CHECKOUT` is a maintainer comparison
against the original Swift activity reader and native tree renderer. It covers
the supported fixture intersection. The app needs neither that checkout nor Swift.
