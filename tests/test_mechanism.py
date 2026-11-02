import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MechanismTests(unittest.TestCase):
    def test_extracted_symbols_match_recorded_original_hashes(self):
        source = (ROOT / 'src/trace_mechanism/parser.py').read_text()
        lines = source.splitlines(keepends=True)
        tree = ast.parse(source)
        nodes = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        recorded = json.loads((ROOT / 'docs/provenance.json').read_text())['symbol_sha256']
        for name, expected in recorded.items():
            node = nodes[name]
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            block = ''.join(lines[start - 1:node.end_lineno])
            self.assertEqual(hashlib.sha256(block.encode()).hexdigest(), expected, name)

    def test_synthetic_examples_match_expected_output(self):
        for provider in ('codex', 'claude'):
            actual = subprocess.check_output([sys.executable, '-m', 'trace_mechanism', provider,
                                              str(ROOT / f'examples/{provider}.jsonl')], text=True)
            self.assertEqual(json.loads(actual), json.loads((ROOT / f'examples/{provider}.expected.json').read_text()))

    def test_missing_result_is_explicit(self):
        data = json.loads((ROOT / 'examples/codex.expected.json').read_text())
        self.assertFalse(data[0]['complete'])
        self.assertEqual(data[0]['tools'][1]['output'], '[no output recorded]')
        self.assertIn('without function_call_output', data[0]['partial_reason'])


if __name__ == '__main__':
    unittest.main()
