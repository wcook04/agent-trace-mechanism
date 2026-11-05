---
title: What happened
slot: F3
cockpit_slot: F3
status: ready
when_to_use: Reading what an agent actually did
---

# What actually happened here

Below is a trace of an agent session. Tell me what it did.

Not what it said it did. Traces contain both, and the gap between them is the whole reason to read one.

Go through it and separate:

- **Ran and passed.** A command executed and its output shows the result. Quote the output.
- **Ran and failed.** Including failures the session recovered from — those are often the most informative part.
- **Claimed without running.** Anything asserted in prose with no command behind it.
- **Started and abandoned.** Work that was begun and then dropped, whether or not that was noticed.

Then answer three questions:

1. Did it finish what it was asked to do? If partly, which part is missing?
2. Is there anything it broke that it did not notice? Look for edits that were never followed by a test run, and tests that changed expectations rather than fixing code.
3. Where did it change direction, and what caused that? A reversal usually marks the point where the real problem was found.

Be concrete. Cite the line or command you are describing. If the trace is truncated and you cannot tell, say so rather than inferring.

---

TRACE:
