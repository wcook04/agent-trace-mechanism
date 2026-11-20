# Reading a worker's saved run in another chat

On 17 November 2026, a Codex worker finished a task on a small web service and reported:

> All 42 tests passed. Live responses match OpenAPI, and older standalone inputs still load without the reading-path receipts.

On 20 November that worker's saved session was exported as one ZIP file, a capture, containing its 196 recorded items and a small standard-library reader. A Claude model (Opus) and a fresh GPT reviewer in ChatGPT each received the capture, the worker's report and the same question. Each chose which recorded commands and results to read and returned references to the evidence it used.

The reviewers were instructed to use only the capture. Claude ran on the originating machine; its recorded tool calls were checked afterwards for compliance with that instruction. GPT received the uploaded capture without the original project. The fresh GPT reviewer wrote its answer before seeing Claude's verdict. The later comparison and implementation audit were separate activities.

The capture was then imported into Agent Trace on the originating machine. All 12 of Claude's references and all 9 of GPT's reopened at the saved text. The installed MCP tool also reopened the live-HTTP reference and supplied a follow-up read pinned to the same snapshot.

## The worker's report against its own records

Each sentence of the report has a recorded command that exited 0. The two schema checks finished before the worker's last edit, and the 42-test run finished after it. That last edit, at 20:09:51 UTC, changed one test in `test_service.py` by adding `len(fields) == 5` to a condition. The quoted outputs below come from the private capture.

| Sentence of the report | Recorded command | Finished (UTC) | Text at the citation |
|---|---|---|---|
| "older standalone inputs still load" | A script run with `uv run --with jsonschema` over the bundled and the older data folders | 20:09:09 | `Draft 2020-12 validates bundled and legacy study and sources payloads.` |
| "Live responses match OpenAPI" | An inline script that started the service on a local port, fetched the study routes over HTTP and validated each response against `/openapi.json` | 20:09:40 | `Live JSON study aliases and sources match OpenAPI schemas.` |
| "All 42 tests passed." | `python3 -B -m unittest discover && python3 -B verification/check_bundle.py && git diff --check` | 20:09:55 | `Ran 42 tests in 0.943s` · `OK` · `Verified 34 pinned files and 30 case records.` |

A reader of the record can open that edit and judge whether it changes what the two earlier checks show.

Earlier in the same session, a `unittest discover` run failed with `Ran 37 tests in 0.864s` and `FAILED (errors=10`. The worker made further edits after it, and the 42-test run came after the last of them.

The records do not show which 42 tests ran, because the output shows only dots. They do not show the environment the command inherited. The test code reads `cls.data_dir = Path(os.environ.get("MEDAGENT_TEST_DATA_DIR", ROOT / "data"`, and the final command does not set that variable. The capture contains only this worker, so it cannot show whether the parent chat or another worker changed shared files afterwards.

## What each reviewer did

Both reviewers were asked whether "All 42 tests passed" established that the complete relevant suite passed against the worker's final code. Both answered "supported only in narrower form". That question asked about more than the worker had said.

Claude found the final 42-test run, the earlier failing run and the data-folder default. It said the 42 tests used only the bundled data. It also discussed a separate schema-validation script without citing the successful live HTTP check.

The independent GPT reviewer found the same final run and earlier failure. It also found and cited the successful live HTTP check.

When the two reviews were compared afterwards, Claude's statement about the data folder turned out to go further than the record. The final command does not set `MEDAGENT_TEST_DATA_DIR`, but the record does not show the environment the command inherited, so it cannot show that the variable was unset. Neither reviewer could inspect that environment.

Because the references reopen, the reviews can be checked as well as the worker. One of Claude's references opens at only `MEDAGENT_TEST_DATA_DIR`, which is too short to show the claim written beside it. A reference can resolve correctly while its text does not support the sentence next to it.

## What changed in the reader

A separate implementation audit in the same research round found defects in the reader and exporter. The following fixes were then applied and checked in the desktop environment.

In the desktop app's MCP server, opening a citation already read the saved snapshot. But the follow-up read that the result suggested left out the snapshot ID, and the server reads the live session when that ID is missing. So a reviewer following the suggestion could move to newer text without being told. The suggested read now carries the snapshot ID.

A short page of a whole item used to be cited as the whole item. It is now cited with its character range. Search results also give a second citation for the passage shown, beside the citation for the matched text.

A later review of the published reader found that a damaged citation could still resolve to different text. The parser ignored unknown query parameters and kept the last of two repeated ones. So `&amp;chars=0-4`, left over from copying through HTML, or a typo such as `&char=0-4`, returned the whole field, and `&chars=0-4&chars=11-15` returned the second range. The reader now refuses unknown, repeated or HTML-escaped parameters, reports the bad citation, and goes on with the rest of a batch. [`tests/test_citation_queries.py`](../../tests/test_citation_queries.py) has the cases.

## Try the reader on a different published capture

The worker's capture and complete review records are not published here, because the capture contains outputs from a private repository. The download below lets a reader reproduce the search, read and citation mechanics on different evidence; it does not reproduce the private Bernoulli comparison. [`examples/portable-capture/validation-history.trace.zip`](../../examples/portable-capture/validation-history.trace.zip) is a capture of the five published records from [Checking a worker's validation history](investigation.md): a failing test run, a fixture correction and a passing retry. A test in [`tests/test_portable_capture.py`](../../tests/test_portable_capture.py) checks that its snapshot is exactly what the native reader produces from [`examples/validation-history/validation-history.jsonl`](../../examples/validation-history/validation-history.jsonl).

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
- The shared artifact was the same capture. Claude's restriction was procedural; GPT's copy did not include the original project. The blind capture review, subsequent comparison and implementation audit were distinct steps.
- Nothing in the capture was rerun. The records describe the code as it was on 17 November.
- The export tool that made these captures is in the private desktop build of Agent Trace. This repository has the reader and the published capture, and does not yet have the exporter.
- A capture contains whatever the session saved, including paths and command output. Read one before sharing it.

