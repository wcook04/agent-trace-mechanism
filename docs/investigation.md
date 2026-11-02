# Checking a worker's validation history

[README](../README.md) · [Selected native records](../examples/validation-history.jsonl) · [Provenance](../examples/validation-history-provenance.json)

During Agent Trace development on 2 November 2026, a reviewing agent used the public MCP server to investigate test failures across an existing chat and its 16 descendants. The records showed why an isolated successful command was insufficient evidence.

## What the records showed

| Time (UTC) | Recorded operation | What it establishes |
|---|---|---|
| 20:20:17 | Parser tests: 60 passed | One test file passed at that time. |
| 20:30:50 | Parser and workbench tests: 123 passed, 1 failed | The later combined run failed an output-attribution assertion. |
| 20:31:04 | Fixture correction, dry run | A proposed change was displayed; it was not applied. |
| 20:31:09 | Fixture correction, live apply | The recorded patch replaced hand-escaped JSON with `JSON.stringify` in the test fixture. |
| 20:31:10 | Combined retry: 124 passed, 0 failed | The retained test output reports a successful retry. |

The retry command pipes output to `tail -10`, so its exit code alone would not establish that the tests passed. The retained output supplies the test counts. This sequence records a fixture correction and its validation; it does not establish the state of a later checkout.

## How the agent found it

The agent started with the known parent chat, without a worker or command ID. Searching failed commands for `test` was too broad; `test_agent_tools` found shell searches rather than failed tests. Searching for `AssertionError` identified the relevant worker. The agent then used the failed test's name and the observed command to find the surrounding attempts, reading individual commands and outputs from the retained capture.

While the parent chat continued, a fresh comparison reported 16 changed items. Reading the old failed command again returned identical content. The next comparison page used the same two capture endpoints. No records were appended or removed to manufacture this check.

This was a maintainer-assisted investigation of existing work, not a blind agent evaluation. Only the five relevant commands are published. Their IDs, timestamps and outputs are retained; the checkout path is replaced and session metadata reduced.

After [installation](mcp.md#setup), retrieve and check those records through a separate MCP server process:

```sh
.venv/bin/python tools/inspect_recorded_run.py
```

The script prints the sequence and verifies retrieved commands and outputs against the selected source. It does not execute the historical commands or repeat the agent's discovery process.

## Retrieval costs

A separate measurement used a frozen copy of that worker's full 5.57 MB history, not the five-record selection. Both MCP and `rg` read identical bytes. Three sequential measurements on macOS arm64, Python 3.12.7; medians below. Server initialization is excluded and filesystem caches were not cleared.

| Operation | Median | Returned bytes |
|---|---:|---:|
| Fresh capture and failed-command search | 30.18 ms | 9,738 |
| Same search in the retained capture | 2.25 ms | 9,738 |
| Read one retained output field | 0.75 ms | 8,537 |
| `rg -n -i -F AssertionError` | 4.57 ms | 333,004 |

Plain search was faster than a fresh MCP capture and could find the same assertion text. It returned 21 whole JSONL lines; MCP returned three failed-command descriptors. The smaller response reflects selection and formatting, not proof of better search quality. MCP byte counts include both serialized result representations; these are not token measurements. Snapshot memory growth was not measured.

[All measurements](../examples/retrieval-costs.json) include individual timings and the source hash. To measure a local native history containing a failed command:

```sh
.venv/bin/python tools/measure_retrieval.py /path/to/rollout.jsonl --query AssertionError
```

The command prints measurements without printing history contents. `rg` is optional.
