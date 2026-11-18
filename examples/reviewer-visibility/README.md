# Reviewer visibility example

The files behind [the write-up](../../docs/studies/reviewer-visibility.md). There is one folder for each test.

| Folder | The test |
|---|---|
| [earlier-turns/](earlier-turns/) | Two scripted conversations with the same last turn. Models were given only the last turn and asked whether the user had agreed to a deletion. This is the test with the table in the write-up |
| [tool-output/](tool-output/) | One recorded conversation and two edited versions of it. Models were given copies with the tool output left out |
| [pasting-back/](pasting-back/) | One Codex session forked six times. A scripted review was pasted into each fork, three times with the lines from Agent Trace and three times without |
| [first-pass/](first-pass/) | The first version of the tool-output test, kept as it was. Its copies had a defect that the write-up describes |

`earlier-turns/` and `tool-output/` have the same layout:

| File | Contents |
|---|---|
| `conversations/` | The saved conversations. In `earlier-turns/` both were written by a script and are not recordings. In `tool-output/`, `told.jsonl` is a recording with private records removed, and the other two are that recording with two edits |
| `copies/` | The exact text each model was given, named `<conversation>.<copy>.txt` |
| `prompt.txt` | The prompt, with a copy in place of `{copy}` |
| `replies/` | Each reply as the model wrote it, in a folder for each model, named `<conversation>.<copy>.<run>.txt` |
| `return-note.txt` | The lines Agent Trace writes to send to the coding agent with a reply |

Three files belong to one test only. [earlier-turns/next-step-readings.json](earlier-turns/next-step-readings.json) is a reading of what each reply told the user to do next. [earlier-turns/discarded-first-run/](earlier-turns/discarded-first-run/) holds 40 replies that were thrown away because a chat message of mine had been passed to the models. [tool-output/inventory.json](tool-output/inventory.json) holds the counts that the lines for `told` are written from.

[results.json](results.json) has every answer from every reply, with its score and the key the scores use. [provenance.json](provenance.json) says how each file was made and which files are not regenerated.

Where two copies have the same text, that text was given to the models once. In `tool-output/` those replies are filed under `told`, and in `earlier-turns/` under `agreed`.

To check that the copies and the scores match the code:

```sh
python tools/build_visibility_example.py --check
python tools/score_visibility_reviews.py --check
```
