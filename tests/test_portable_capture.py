"""The published capture holds exactly the published records, and a reader with only the ZIP can cite them."""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from trace_mechanism import capture_reader as reader
from trace_mechanism import codex_native

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / 'examples/portable-capture/validation-history.trace.zip'
SOURCE = ROOT / 'examples/validation-history/validation-history.jsonl'


class PublishedCapture(unittest.TestCase):
    def setUp(self):
        self.cap = reader.Capture.open(CAPTURE)

    def test_window_is_the_native_snapshot_of_the_published_records(self):
        native = codex_native.load_rollout(SOURCE)
        native['source'].pop('path', None)
        self.assertEqual(list(self.cap.windows), [native['sha256']])
        self.assertEqual(self.cap.windows[native['sha256']], native)

    def test_bundled_reader_is_the_package_reader(self):
        with zipfile.ZipFile(CAPTURE) as z:
            bundled = z.read('capture_reader.py')
        self.assertEqual(bundled, (ROOT / 'src/trace_mechanism/capture_reader.py').read_bytes())

    def test_isolated_reader_finds_and_cites_the_retry_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(CAPTURE) as z:
                z.extractall(tmp)

            def run(*args):
                done = subprocess.run([sys.executable, '-I', 'capture_reader.py', *args], cwd=tmp,
                                      capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                return json.loads(done.stdout)

            self.assertTrue(run('verify')['verified'])
            hit = run('search_contents', '--query', 'pass 124')['hits'][0]
            self.assertEqual(hit['field'], '/aggregated_output')
            resolved = run('cite', hit['cite'])['results'][0]
            self.assertTrue(resolved['resolved'])
            self.assertEqual(resolved['text'], 'pass 124')

    def test_wrong_snapshot_is_refused(self):
        bad = reader.make_cite('0' * 64, 'any-item', '/aggregated_output', 0, 3)
        self.assertFalse(reader.cite(self.cap, [bad])['results'][0]['resolved'])


if __name__ == '__main__':
    unittest.main()
