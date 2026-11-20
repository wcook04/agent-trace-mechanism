# Reading a worker's saved run in another chat

Codex and Claude Code save each session as a file on your computer. Agent Trace is a tool that reads those files. This page is about one new thing it can do: export one saved session as a single ZIP file, called a capture, so that a model in a different chat, such as ChatGPT, can read the session without any access to the machine where the session was recorded.

The example is a real Codex worker, a sub-agent that a Codex chat starts to do one task. The worker reported that its tests passed. Its session was exported as a capture, and two models, Claude and GPT, were each given the capture and asked whether the saved session showed what the worker had claimed.

**The result in brief.** Each of the worker's three claims has a command in its saved session that finished with exit code 0. Both models found the final test run. GPT also found a command that sent requests to the web service over HTTP and validated the responses, which Claude did not cite. Each model gave references for the saved text it quoted, 21 in all, and when the capture was imported back into Agent Trace, all 21 opened at the quoted text. Reading the text that Claude's references opened showed that one of Claude's statements, about which test data the tests used, went further than the saved session can show. Separately, two reviews of Agent Trace's code found three faults in how it handled references, and they are now fixed.

## What a capture contains

A capture is one ZIP file with three things in it:

- the saved session, as it was at the moment of export: every command the worker ran, each command's output and exit code, every file edit and every message;
- a manifest listing what was included, what was left out, and a SHA-256 hash of each file in the ZIP;
- `capture_reader.py`, a short Python script that needs nothing but Python 3.9 or later. The script verifies the hashes, lists the saved items, searches their text and prints any item or any range of characters from it.

The exported session gets an ID, the SHA-256 hash of its contents, called the snapshot ID. Each saved command, output, edit or message has its own item ID, taken from the session file.

Every time the script prints text, it also prints a reference to that text, for example:

```text
agent-trace://99b68b39…/exec-31ac40f6-…?field=/aggregated_output&chars=11598-11606
```

(The two IDs are shortened here. The full reference appears in the commands at the end of this page.) The reference names the snapshot ID, the item ID, the field inside that item (here `aggregated_output`, the command's output) and the character range. A reviewer who quotes saved text in an answer gives the reference beside the quote. Later, on the machine where the session was recorded, Agent Trace can import the capture and open each reference at the same characters. The session file may have grown since the export, but the reference still opens the text as it was when exported.

## The worker and its report

On 17 November 2026, a Codex worker finished changing a small Python web service that returns data about a study as JSON. It ended with this message:

> The existing study endpoint now serves the five-step reading path, its verified receipt checksum, and a link with a JSON Pointer. Clients can follow that link to the existing sources endpoint to resolve claim IDs, values, and provenance.
>
> All 42 tests passed. Live responses match OpenAPI, and older standalone inputs still load without the reading-path receipts.

The first paragraph says what the worker changed: the service's study endpoint now also returns a five-step reading path and a checksum for it, which the worker calls a receipt. The second paragraph makes three claims. The test suite passed. The service's responses over HTTP match its OpenAPI description. Older input files, made before the receipts existed, still load.

On 20 November the worker's session was exported as a capture with 196 saved items. The capture is not published, because the worker read files from a private repository and their contents are in its saved outputs. The quoted outputs on this page are short ranges from it.

## What the saved session shows

Each of the three claims in the message has a command in the session that exited with code 0. This table lists them in the order they finished.

| Claim in the message | Command the worker ran | Finished (UTC) | Output at the reference |
|---|---|---|---|
| "older standalone inputs still load" | A script, run with `uv run --with jsonschema`, that built the study and sources data from the service's bundled data folder and from its older data folder, and validated both against the service's JSON Schema | 20:09:09 | `Draft 2020-12 validates bundled and legacy study and sources payloads.` |
| "Live responses match OpenAPI" | A script that started the web service on a local port, requested its study endpoints over HTTP and validated each response against the service's `/openapi.json` | 20:09:40 | `Live JSON study aliases and sources match OpenAPI schemas.` |
| "All 42 tests passed." | `python3 -B -m unittest discover && python3 -B verification/check_bundle.py && git diff --check` | 20:09:55 | `Ran 42 tests in 0.943s` · `OK` · `Verified 34 pinned files and 30 case records.` |

The third command runs three steps joined by `&&`, so each step runs only if the one before it succeeded: the unit tests, then the service's own script that verifies its bundled files, then git's whitespace check on the working tree. The whole command exited with code 0.

The worker's last file edit finished at 20:09:51, between the second and third commands. That edit changed one test in `test_service.py`, adding `len(fields) == 5` to a condition. So the 42-test run came after the last edit, and the first two commands in the table came before it. Anyone reading the capture can open that edit and decide whether it affects what the first two commands showed.

Earlier in the same session, `python3 -B -m unittest discover` had failed with `Ran 37 tests in 0.864s` and `FAILED (errors=10`. The worker made several edits after that failure, and the 42-test run was after the last of them.

There are three things the saved session cannot show:

- **Which 42 tests ran.** The test output prints one dot per test and no test names.
- **The environment variables the test command started with.** The tests choose their data folder with `cls.data_dir = Path(os.environ.get("MEDAGENT_TEST_DATA_DIR", ROOT / "data"`, so they use the bundled `data` folder unless `MEDAGENT_TEST_DATA_DIR` is set. The command line does not set it. Whether it was already set in the shell is not recorded.
- **Changes made by other agents.** The capture holds only this worker's session. If the Codex chat that started the worker, or another worker, changed shared files later, that is not in this capture.

## What the two reviewers did

Two models reviewed the capture:

- **Claude (Opus)**, on the machine where the session was recorded, was told to use only the capture and the script inside it. Its tool calls were read afterwards. All 13 were shell commands in the capture's folder, and it opened no other file.
- **GPT**, in a new ChatGPT session, got the capture as an upload, with no access to the machine. It wrote its answer before seeing Claude's.

Both got the worker's message and the same question: does the saved session show that "All 42 tests passed" means the complete relevant test suite passed on the worker's final code? The worker had said only that 42 tests passed. The question also asked whether those 42 were all the relevant tests and whether they ran on the final code, which the worker had not claimed.

Both models answered "supported only in a narrower form", and both stated the narrower claim. Claude's was that after the worker's last edit, `unittest discover` ran 42 tests with the default data folder and all of them passed. GPT's was that the final `unittest discover` run passed all 42 tests it found after the worker's last edit, and that the saved session does not show whether those were all the relevant tests or what the whole code looked like at the end.

Claude cited the 42-test run, the earlier failing run, and the line in the tests that falls back to the bundled data folder. Claude wrote that the 42 tests used only the bundled data. Claude did not cite the second command in the table, the one that requested the live endpoints over HTTP.

GPT cited the same 42-test run and the same earlier failure. GPT also found and cited the command that requested the live endpoints over HTTP and validated the responses.

The capture was then imported into Agent Trace on the machine where the session was recorded. All 12 of Claude's references and all 9 of GPT's opened at the text each model had quoted.

When the two answers were read against the text their references opened, two problems were found in Claude's answer:

- Claude's statement that the tests used only the bundled data goes further than the session shows. The command line does not set `MEDAGENT_TEST_DATA_DIR`, but the session does not record whether the shell already had it set.
- One of Claude's references opens at only the 22 characters `MEDAGENT_TEST_DATA_DIR`. That text is what Claude quoted, but those 22 characters cannot support the sentence Claude wrote next to them. A reference can open at exactly the right text while the text is still not enough to support what the reviewer says about it.

## Faults found in Agent Trace and fixed

Two later reviews of Agent Trace's code, done in ChatGPT, found three faults in how references were handled. All three are fixed.

1. **A follow-up read could leave the saved snapshot.** Agent Trace includes an MCP server, which lets Claude Code and Codex call Agent Trace as a tool. When that server opened a reference, it read the saved snapshot correctly. It also suggested the next read for the reviewer to make, but the suggested read left out the snapshot ID. Without a snapshot ID, the server reads the session file as it is now. So a reviewer following the suggestion would have read newer text without being told. The suggested read now includes the snapshot ID.
2. **A short read was cited as the whole item.** When the script printed a short range of a long item, the reference it gave pointed at the whole item. The reference now includes the character range. Search results now give two references: one for the matched words and one for the passage printed around them.
3. **A damaged reference could open different text.** The script ignored parts of a reference it did not recognise, and when a part appeared twice it used the second one. So a reference copied through HTML (with `&amp;chars=0-4` in place of `&chars=0-4`) or one with a typo (`&char=0-4`) opened the whole output instead of the four characters. A reference with `&chars=0-4&chars=11-15` opened the second range. The script now refuses a reference with an unknown, repeated or HTML-escaped part, says which reference it refused, and carries on with any others it was given. [`tests/test_citation_queries.py`](../../tests/test_citation_queries.py) has these cases.

## Try the script on a published capture

[`examples/portable-capture/validation-history.trace.zip`](../../examples/portable-capture/validation-history.trace.zip) is a different, smaller capture that you can download. It holds the five saved commands published in [Checking a worker's validation history](investigation.md): a test run that passed, a larger test run that failed, a dry run and then a real run of a correction to a test fixture, and a retry of the larger test run that passed. It shows how the script works. It is not the worker's capture described above. A test in [`tests/test_portable_capture.py`](../../tests/test_portable_capture.py) confirms that its saved session matches exactly what Agent Trace reads from [`examples/validation-history/validation-history.jsonl`](../../examples/validation-history/validation-history.jsonl).

Unzip it anywhere and run the script inside it with Python 3.9 or later:

```sh
unzip validation-history.trace.zip -d capture && cd capture
python3 capture_reader.py verify
python3 capture_reader.py list_items --kind CommandExecution
python3 capture_reader.py search_contents --query "pass 124"
python3 capture_reader.py cite "agent-trace://99b68b3932508387b45581f54c62cdbe78fb19cbfb98d1b6a32f045f70212164/exec-31ac40f6-d9e0-4099-ae13-4096e65285ac?field=/aggregated_output&chars=11598-11606"
```

- `verify` recomputes every hash and prints `"verified": true` if the files are unchanged.
- `list_items --kind CommandExecution` lists the five commands, each with its exit code.
- `search_contents --query "pass 124"` finds the line `pass 124` in the output of the retry that passed. It prints the reference `…/exec-09178280-9355-47f4-a6ce-b1d912cc9dab?field=/aggregated_output&chars=225-233`.
- `cite` opens the reference you give it. This one prints `pass 123`, from the larger test run that failed, which exited with code 1.

The retry's command ends in `| tail -10`. Unless the shell had `pipefail` set, the exit code of 0 belongs to `tail`, not to the tests, so the number of passing tests has to be read from the output.

The script's command names follow the history tools Codex gives its models: `list_items`, `read_item` (which takes `offset_chars` and `limit_chars`) and `search_contents`. In the script, the option `--window-id` takes a snapshot ID. In Codex, a window is a model's context window, which is a different thing. If you give the script a snapshot ID that is not in the capture, it refuses and does not read any other version. The script's source is [`src/trace_mechanism/capture_reader.py`](../../src/trace_mechanism/capture_reader.py).

## Limits

- This is one worker and two reviews. It says nothing about how often reviews like these are right.
- Claude ran on the machine where the session was recorded and was told to use only the capture, so its access was limited by instruction, not by the machine. GPT had only the uploaded capture.
- Nothing in the capture was run again. The saved session describes the web service's code as it was on 17 November.
- The export tool that makes captures is in the desktop version of Agent Trace, which is not public. This repository has the script and the published capture, and does not yet have the export tool.
- A capture contains whatever the session saved, including file paths and command output. Read a capture before sharing it.
