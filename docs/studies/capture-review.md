# Two models reviewing a Codex worker from a saved copy of its run

On 17 November 2026, a Codex worker finished a task on a small web service and reported:

> All 42 tests passed. Live responses match OpenAPI, and older standalone inputs still load without the reading-path receipts.

On 20 November that worker's saved session was exported as one ZIP file, a capture, containing its 196 recorded items and a small standard-library reader. A Claude model (Opus) and then a GPT model in a ChatGPT session each got the capture, the worker's report and one question, and nothing else. Neither could open the original session or the project. Each reviewer chose its own reads and cited the records it used. The capture was then imported into Agent Trace on the machine that recorded the run, and every citation was opened there. All 12 of Claude's and all 9 of GPT's opened at the saved text.

## The worker's report against its own records

Each sentence of the report has a recorded command that ran after the worker's last edit and exited 0. These are the cited ranges.

| Sentence of the report | Recorded command | Text at the citation |
|---|---|---|
| "All 42 tests passed." | `python3 -B -m unittest discover && python3 -B verification/check_bundle.py && git diff --check` | `Ran 42 tests in 0.943s` · `OK` · `Verified 34 pinned files and 30 case records.` |
| "Live responses match OpenAPI" | An inline script that started the service on a local port, fetched the study routes over HTTP and validated each response against `/openapi.json` | `Live JSON study aliases and sources match OpenAPI schemas.` |
| "older standalone inputs still load" | A script run with `uv run --with jsonschema` over the bundled and the older data folders | `Draft 2020-12 validates bundled and legacy study and sources payloads.` |

Earlier in the same session, a `unittest discover` run failed with `Ran 37 tests in 0.864s` and `FAILED (errors=10`. The worker made further edits after it, and the 42-test run came after the last of them.

The records do not show which 42 tests ran, because the output shows only dots. They do not show the environment the command inherited. The test code reads `cls.data_dir = Path(os.environ.get("MEDAGENT_TEST_DATA_DIR", ROOT / "data"`, and the final command does not set that variable. The capture contains only this worker, so it cannot show whether the parent chat or another worker changed shared files afterwards.

## What each reviewer did

Both reviewers were asked whether "All 42 tests passed" established that the complete relevant suite passed against the worker's final code. Both answered "supported only in narrower form". That question asked about more than the worker had said.

Claude made 13 tool calls and cited 12 ranges. It found the final 42-test run, the earlier failing run and the data-folder default. It said the 42 tests used only the bundled data. It also said the OpenAPI claim rested on a separate script, and it did not cite the live HTTP run.

GPT made 29 reader calls and cited 9 ranges. It found the same final run and the same earlier failure. It also found the live HTTP run, and it gave the environment point more carefully: the command does not set the variable, so the record cannot show whether the variable was set.

Reading the two reviews side by side against the citations shows that GPT's account is the fairer one to the worker. One of Claude's citations opens at only `MEDAGENT_TEST_DATA_DIR`, which is too short to show the claim written beside it. A citation can open correctly and still not support its sentence, so the person checking the review still has to read the cited text.

## What changed in the reader

GPT's review also covered the reader and exporter code, and its findings are now fixed.

In the desktop app's MCP server, opening a citation already read the saved snapshot. But the follow-up read that the result suggested left out the snapshot ID, and the server reads the live session when that ID is missing. So a reviewer following the suggestion could move to newer text without being told. The suggested read now carries the snapshot ID.

A short page of a whole item used to be cited as the whole item. It is now cited with its character range. Search results also give a second citation for the passage shown, beside the citation for the matched text.

## Try it on a published capture

The worker's capture is not published, because the worker read files in a private repository and their contents are in its outputs. [`examples/portable-capture/validation-history.trace.zip`](../../examples/portable-capture/validation-history.trace.zip) is a capture of the five published records from [Checking a worker's validation history](investigation.md): a failing test run, a fixture correction and a passing retry. A test in [`tests/test_portable_capture.py`](../../tests/test_portable_capture.py) checks that its snapshot is exactly what the native reader produces from [`examples/validation-history/validation-history.jsonl`](../../examples/validation-history/validation-history.jsonl).

Unzip it anywhere and run the bundled reader. It needs Python 3.9 or later and nothing else.

```sh
unzip validation-history.trace.zip -d capture && cd capture
python3 capture_reader.py verify
python3 capture_reader.py list_items --kind CommandExecution
python3 capture_reader.py search_contents --query "pass 124"
python3 capture_reader.py cite "agent-trace://99b68b3932508387b45581f54c62cdbe78fb19cbfb98d1b6a32f045f70212164/exec-31ac40f6-d9e0-4099-ae13-4096e65285ac?field=/aggregated_output&chars=11598-11606"
```

The last command prints `pass 123` from the combined run that exited 1. The search finds `pass 124` in the retry, at `…/exec-09178280-9355-47f4-a6ce-b1d912cc9dab?field=/aggregated_output&chars=225-233`. The retry's command ends in `| tail -10`. Unless the shell set `pipefail`, its exit code of 0 is the exit code of `tail`, so the test counts have to come from its output.

A citation names the snapshot ID, the item ID, a JSON Pointer to the field and a character range. If the snapshot ID is not in the capture, the reader refuses it rather than reading another version. The command names follow Codex's history tools (`list_items`, `read_item` with `offset_chars` and `limit_chars`, `search_contents`). Here a `window_id` is a frozen snapshot of one conversation, not a model context window. The reader's source is [`src/trace_mechanism/capture_reader.py`](../../src/trace_mechanism/capture_reader.py).

## Limits

- This is one worker and two reviews, so it says nothing about how often reviews like these are right.
- Both reviewers read the same capture. Claude ran on the recording machine with an instruction not to open other files, and its tool calls were checked afterwards. GPT ran in ChatGPT with the capture uploaded.
- Nothing in the capture was rerun. The records describe the code as it was on 17 November.
- The export tool that made these captures is in the private desktop build of Agent Trace. This repository has the reader and the published capture, and does not yet have the exporter.
- A capture contains whatever the session saved, including paths and command output. Read one before sharing it.
