"""Semantic checks against selected real records and the published interpretations."""
import hashlib
import json
from pathlib import Path
import unittest

from trace_mechanism.parser import parse_codex_session

ROOT = Path(__file__).resolve().parents[1]


class RecordedExamplesTests(unittest.TestCase):
    def test_delivered_requests_and_result_are_retained(self):
        turns = parse_codex_session(ROOT / 'examples/codex-retrieval/source-after.jsonl')
        self.assertEqual(len(turns), 2)
        self.assertIn('10:00', turns[0].prompt_text)
        self.assertIn('10:30', turns[1].prompt_text)
        self.assertTrue(all(t.turn_ended and t.tool_evidence_complete for t in turns))
        self.assertEqual(len(turns[0].tool_events), 1)
        self.assertIn('21', turns[0].tool_events[0].output_text)
        self.assertEqual(turns[1].tool_events, [])

    def test_index_final_answer_points_to_recorded_source(self):
        directory = ROOT / 'examples/codex-retrieval'
        clip = json.loads((directory / 'after.index.json').read_text())
        message = clip['terminal_state_index']['final_assistant_message']
        lines = (directory / 'after.detailed.txt').read_text().splitlines()
        source = lines[message['line_range']['start'] - 1]
        self.assertEqual(json.loads(source.removeprefix('ASSISTANT: ')), message['body'])
        self.assertIn('10:30', message['body'])
        self.assertFalse(clip['coverage_scope']['full_thread_coverage'])
        self.assertEqual(clip['coverage_scope']['original_session_coverage'], 'unknown_from_supplied_text')

    def test_small_edit_fixture_interpretation(self):
        clip = json.loads((ROOT / 'examples/production-structured-clip.json').read_text())
        rows = clip['artifact_delta_index']['rows']
        self.assertEqual([r['delta_state'] for r in rows], ['discovered', 'edited'])
        self.assertEqual({r['path'] for r in rows}, {'example.txt'})
        self.assertEqual(clip['command_ledger']['command_count'], 1)
        self.assertEqual(clip['command_ledger']['records'][0]['status'], 'not_detected')

    def test_historical_index_does_not_promote_instructions_to_edits(self):
        clip = json.loads((ROOT / 'examples/controlled-run/structured-attachment.json').read_text())
        self.assertNotIn('committed', clip['artifact_delta_index']['state_counts'])
        self.assertNotIn('edited', clip['artifact_delta_index']['state_counts'])
        self.assertEqual(clip['validation_matrix']['command_validation_count'], 1)
        self.assertFalse(clip['coverage_scope']['full_thread_coverage'])
        self.assertEqual(len(clip['agent_episode_graph']['observed_scope_labels']), 3)
        self.assertEqual(len(clip['agent_episode_graph']['observed_delegations']), 2)
        self.assertIn('not chronology or parent-child identity', clip['agent_episode_graph']['graph_semantics'])
        self.assertIn('sibling raw sidecar', clip['local_capture']['note'])

    def test_copied_builder_matches_pinned_source(self):
        provenance = json.loads((ROOT / 'docs/structurer-provenance.json').read_text())
        self.assertEqual(hashlib.sha256((ROOT / provenance['copy']).read_bytes()).hexdigest(), provenance['sha256'])


if __name__ == '__main__':
    unittest.main()
