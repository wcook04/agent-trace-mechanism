# Portable capture example

`validation-history.trace.zip` holds the five published records in [`../validation-history/`](../validation-history/) as one capture file. It contains the native snapshot of those records, a manifest and `capture_reader.py`, a reader that needs only Python 3.9 or later.

```sh
unzip validation-history.trace.zip -d capture && cd capture
python3 capture_reader.py verify
python3 capture_reader.py search_contents --query "pass 124"
```

[`provenance.json`](provenance.json) gives the hashes of the capture and its source file. The study [Two models reviewing a Codex worker from a saved copy of its run](../../docs/studies/capture-review.md) explains how captures were used on a real worker.
