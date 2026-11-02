import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from trace_mechanism.parser import parse_codex_session, parse_claude_session
from trace_mechanism.replay import replay, records
from trace_mechanism.agent_tools import AgentTools
from trace_mechanism.views import render, structured

ROOT = Path(__file__).resolve().parents[1]


class MechanismTests(unittest.TestCase):
    def test_extracted_symbols_match_recorded_original_hashes(self):
        source = (ROOT / 'src/trace_mechanism/parser.py').read_text()
        lines = source.splitlines(keepends=True)
        nodes = {n.name: n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        recorded = json.loads((ROOT / 'docs/provenance.json').read_text())['symbol_sha256']
        for name, expected in recorded.items():
            node = nodes[name]
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            self.assertEqual(hashlib.sha256(''.join(lines[start-1:node.end_lineno]).encode()).hexdigest(), expected, name)

    def test_synthetic_examples_match_expected_output(self):
        for provider in ('codex', 'claude'):
            actual = subprocess.check_output([sys.executable, '-m', 'trace_mechanism', provider,
                                              str(ROOT / ('examples' if provider == 'codex' else 'tests/fixtures') / f'{provider}.jsonl')], text=True)
            self.assertEqual(json.loads(actual), json.loads((ROOT / ('examples' if provider == 'codex' else 'tests/fixtures') / f'{provider}.expected.json').read_text()))

    def test_actual_missing_result_and_view_selection(self):
        for provider, parse in [('codex', parse_codex_session), ('claude', parse_claude_session)]:
            turns = parse(ROOT / ('examples' if provider == 'codex' else 'tests/fixtures') / f'{provider}.jsonl')
            compact, detailed, data = render(turns), render(turns, True), structured(turns)
            self.assertIn('old line', detailed)
            self.assertIn('new line', detailed)
            self.assertNotIn('old line', compact)
            self.assertNotIn('new line', compact)
            self.assertIn('[omitted in compact view]', compact)
            self.assertTrue(any(e['output'].startswith('old line') for e in data[0]['tools']))
        pending = parse_codex_session(ROOT / 'examples/codex.jsonl')[0]
        self.assertFalse(pending.is_complete)
        self.assertEqual(pending.tool_events[-1].output_text, '[no output recorded]')
        self.assertIn('without function_call_output', pending.partial_reason)

    def test_agent_search_scopes_and_stable_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            for provider in ('codex', 'claude'):
                path = Path(directory) / provider
                initial, later, _ = records(provider)
                if provider == 'codex':
                    initial[0]['payload']['id'] = 'test'
                else:
                    initial[0]['sessionId'] = 'test'
                path.write_text(''.join(json.dumps(row) + '\n' for row in initial))
                tools = AgentTools([{'provider': provider, 'session_id': 'test', 'title': 'Example', 'path': path}])
                self.assertEqual(tools.search_trace_threads('example')[0]['provider'], provider)
                self.assertEqual(tools.search_trace_threads('absent'), [])
                with self.assertRaises(ValueError):
                    tools.read_chat_context(provider, 'unknown')
                compact = tools.read_chat_context(provider, 'test')
                self.assertIn('[omitted in compact view]', compact['text'])
                before = tools.read_chat_context(provider, 'test', scope='full_thread', limit=10)
                old = tools.read_trace_page(before['sha256'])['text']
                old_second = tools.read_trace_page(before['sha256'], before['next_offset'], 10)
                with path.open('a') as f:
                    for row in later:
                        f.write(json.dumps(row) + '\n')
                after = tools.read_chat_context(provider, 'test', scope='full_thread')
                self.assertNotEqual(before['sha256'], after['sha256'])
                self.assertEqual(tools.read_trace_page(before['sha256'])['text'], old)
                self.assertEqual(tools.read_trace_page(before['sha256'], before['next_offset'], 10), old_second)
                self.assertEqual(before['text'] + tools.read_trace_page(before['sha256'], before['next_offset'])['text'], old)
                self.assertRegex(after['text'], r'RESULT .+ \(c1\): "ok"')
                self.assertNotRegex(old, r'RESULT .+ \(c1\): "ok"')
                self.assertIn('STATUS: incomplete', old)

    def test_controlled_run_sidecar_and_index_cover_exact_source(self):
        directory = ROOT / 'examples/controlled-run'
        clip = json.loads((directory / 'structured-attachment.json').read_text())
        self.assertEqual(clip['carrier_mode'], 'raw_sidecar_plus_index')
        source = (directory / clip['raw_sidecar']['filename']).read_bytes()
        self.assertEqual(source, (directory / 'assembled.detailed.txt').read_bytes())
        self.assertEqual(len(source), clip['raw_sidecar']['byte_count_utf8'])
        segments = clip['source_segment_index']['segments']
        end = 0
        for segment in segments:
            bounds = segment['byte_range_utf8']
            self.assertEqual(bounds['start'], end)
            chunk = source[bounds['start']:bounds['end']]
            self.assertEqual(len(chunk), segment['byte_count'])
            self.assertEqual(len(chunk.decode('utf-8')), segment['char_count'])
            end = bounds['end']
        self.assertEqual(end, len(source))
        provenance = json.loads((directory / 'provenance.json').read_text())
        for name, recorded in provenance['files'].items():
            data = (directory / name).read_bytes()
            self.assertEqual(len(data), recorded['bytes'], name)
            self.assertEqual(hashlib.sha256(data).hexdigest(), recorded['sha256'], name)

    def test_production_clip_preserves_synthetic_source(self):
        clip = json.loads((ROOT / 'examples/production-structured-clip.json').read_text())
        source = (ROOT / 'examples/codex.detailed.txt').read_bytes()
        segments = sorted(clip['source_segments'], key=lambda item: item['ordinal'])
        self.assertEqual(''.join(item['text'] for item in segments).encode(), source)
        for item in segments:
            bounds = item['byte_range_utf8']
            self.assertEqual(source[bounds['start']:bounds['end']], item['text'].encode())
        provenance = json.loads((ROOT / 'docs/structured-clip-provenance.json').read_text())
        self.assertEqual(hashlib.sha256(source).hexdigest(), provenance['fixture_sha256'])

    def test_explicit_replay_matches_call_and_result(self):
        with tempfile.TemporaryDirectory() as directory:
            for provider in ('codex', 'claude'):
                result = replay(provider, Path(directory) / provider)
                before, after = result['before'][0], result['after'][0]
                self.assertFalse(before['complete'])
                self.assertTrue(before['tools'][0]['missing_result'])
                self.assertTrue(after['complete'])
                self.assertFalse(after['tools'][0]['missing_result'])
                self.assertEqual(after['tools'][0]['call_id'], 'c1')
                self.assertEqual(after['tools'][0]['output'], 'ok')


if __name__ == '__main__':
    unittest.main()
