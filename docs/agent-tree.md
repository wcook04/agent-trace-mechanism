# A real review with two subagents

On 3 November 2026, a fresh coordinator asked two subagents to review the public repository at `c0eec3d`. One inspected file access and network behavior. The other checked setup and supported history formats. They read public source files and returned findings; no private conversation was supplied as context.

The setup reviewer noticed that a relative Python path could fail when the MCP host starts in a different directory. The access reviewer identified that removing a manifest entry does not erase captures already held in memory. The setup guide and security documentation now address both findings.

Run the selected records through the public MCP server:

```sh
.venv/bin/python tools/inspect_agent_tree.py
```

The script searches the coordinator alone, then includes its two registered workers. It retrieves each command's output by its own session/item ID and searches the workers' final answers. The three source files and [manifest](../examples/launch-review/manifest.json) are inspectable; parent links come from the recorded session metadata.

Only one command and the final answer from each session are included. [Provenance](../examples/launch-review/provenance.json) records the original source hashes, selected item IDs and lines, and path replacement. Prompts, injected instructions, reasoning, hooks and other records are omitted. This is a selected recording of actual review work, not a complete raw export. The script verifies retrieval and worker selection; it does not rerun the original review or establish every review conclusion.
