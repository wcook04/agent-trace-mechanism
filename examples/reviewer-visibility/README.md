# Reviewer visibility example

Five histories of one small coding task, the copies of each that reviewers were given, 352 reviews of those copies, and a review pasted back into a forked coding session. [The write-up](../../docs/reviewer-visibility.md) explains it.

| File | Contents |
|---|---|
| [histories/](histories) | `told.jsonl` is a recording with private records removed. `not-told.jsonl` and `wrongly-refused.jsonl` are that recording with two edits made by the build script. `agreed.jsonl` and `forbidden.jsonl` are three-turn conversations written by hand in the build script |
| [copies/](copies) | The texts the reviewers were given, named `<history>.<copy>.txt` |
| [reviewer-prompt.txt](reviewer-prompt.txt), [reviewer-prompt-earlier-turns.txt](reviewer-prompt-earlier-turns.txt) | The prompt each reviewer was given, with a copy in place of `{copy}`. The second is for the copies of `agreed` and `forbidden` |
| [reviews/](reviews) | Each review as the reviewer wrote it, in a folder for each model, named `<history>.<copy>.<run>.txt` |
| [results.json](results.json) | Each answer, its score, and the key the scores use |
| [next-step-readings.json](next-step-readings.json) | For each review of a last-turn copy, a reading of what it told the user to do next |
| [superseded/](superseded) | 40 reviews from the first run of the earlier-turns example, set aside because the reviewers' context held a chat message of mine. The write-up explains |
| [return-note.txt](return-note.txt) | The note to paste beside a review of `told` in the coding conversation |
| [inventory.json](inventory.json) | The counts the notes for `told` are written from |
| [return/](return) | The return leg: a Codex session's compact copy and first report, a scripted review, the two pasted texts, six reports and the commands each fork ran |
| [first-pass/](first-pass) | The copies, reviews and return leg of the first version, kept as they were |
| [provenance.json](provenance.json) | How each file was made, and what is not regenerated |

The compact copies of `told` and `not-told` have the same text, so each of those texts was reviewed once and the review is filed under `told`. The last-turn copies of `agreed` and `forbidden` have the same text too, and those reviews are filed under `agreed`.
