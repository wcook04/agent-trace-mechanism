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
