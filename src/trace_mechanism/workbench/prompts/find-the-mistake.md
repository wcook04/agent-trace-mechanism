---
title: Find the mistake
slot: F4
cockpit_slot: F4
status: ready
when_to_use: Auditing a session that claims success
---

# Find the mistake

Below is a trace of an agent session that believes it succeeded. Assume it is wrong somewhere and find where.

The failures worth hunting, in rough order of how often they hide in a green run:

- **A test that was changed to match the code.** When an assertion was edited after a failure, ask whether the old assertion was right. Changing a test until it passes is the most common way a real defect survives.
- **A check that never ran.** A guard exists in the repository but nothing invokes it. Existence is not wiring — look for the command that would actually execute it.
- **A pipeline that swallowed a failure.** A non-zero exit hidden behind a pipe, a redirect, or a wrapper that returns success regardless.
- **A verified claim that was verified in the wrong place.** A file read from one directory and edited in another; a build that does not compile the tests it claims to cover.
- **Something proven on a warm machine.** Behaviour that depends on state already present — a cache, a config, a file the session itself created earlier — and would fail from a clean start.
- **A fix applied to one instance of a class.** The specimen is repaired and its siblings are not.

For each thing you find, give the evidence in the trace and say what would have caught it. If you cannot find anything, say that plainly rather than manufacturing a finding — but say what you checked, so the absence means something.

---

TRACE:
