import json
from pathlib import Path
import tempfile
import unittest

from trace_mechanism.parser import parse_claude_session, parse_codex_session
from trace_mechanism.views import structured


def parse(parse_fn, rows):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'session.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return parse_fn(path)


def claude_prompt(text):
    return {'type': 'user', 'message': {'role': 'user', 'content': text}}


def codex_event(kind, **payload):
    return {'type': 'event_msg', 'payload': {'type': kind, **payload}}


def codex_response(kind, **payload):
    return {'type': 'response_item', 'payload': {'type': kind, **payload}}


class ParserEvidenceTests(unittest.TestCase):
    def test_orphan_result_is_not_missing_a_result(self):
        cases = [
            (parse_claude_session, [claude_prompt('question'),
                {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'x', 'content': 'Result exists.'}]}},
                {'type': 'assistant', 'message': {'content': [], 'stop_reason': 'end_turn'}}]),
            (parse_codex_session, [codex_event('task_started'),
                codex_response('function_call_output', call_id='x', output='Result exists.'),
                codex_event('task_complete')]),
        ]
        for parser, records in cases:
            with self.subTest(parser=parser.__name__):
                turn = parse(parser, records)[0]
                view = structured([turn])[0]
                tool = view['tools'][0]
                self.assertEqual(tool['output'], 'Result exists.')
                self.assertTrue(tool['result_observed'])
                self.assertFalse(tool['call_observed'])
                self.assertFalse(tool['missing_result'])
                self.assertTrue(tool['missing_call'])
                self.assertTrue(view['turn_ended'])
                self.assertFalse(view['tool_evidence_complete'])
                self.assertFalse(view['complete'])

    def test_ended_turn_with_unresolved_call_remains_incomplete(self):
        cases = [
            (parse_claude_session, [claude_prompt('one'),
                {'type': 'assistant', 'message': {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use', 'id': 'x', 'name': 'read', 'input': {}}]}},
                claude_prompt('two')]),
            (parse_codex_session, [codex_event('task_started'),
                codex_response('function_call', call_id='x', name='read', arguments='{}'),
                codex_event('task_complete')]),
        ]
        for parser, records in cases:
            with self.subTest(parser=parser.__name__):
                view = structured(parse(parser, records))[0]
                self.assertTrue(view['turn_ended'])
                self.assertFalse(view['tool_evidence_complete'])
                self.assertFalse(view['complete'])
                self.assertTrue(view['tools'][0]['missing_result'])
                self.assertIn('without', view['partial_reason'])

    def test_call_without_id_is_retained_without_inventing_an_id(self):
        records = [claude_prompt('question'),
                   {'type': 'assistant', 'message': {'stop_reason': 'tool_use',
                    'content': [{'type': 'tool_use', 'name': 'read', 'input': {}}]}},
                   claude_prompt('next')]
        view = structured(parse(parse_claude_session, records))[0]
        self.assertIsNone(view['tools'][0]['call_id'])
        self.assertTrue(view['tools'][0]['missing_result'])
        self.assertFalse(view['complete'])

    def test_empty_result_is_observed_and_turn_may_still_be_open(self):
        rows = [codex_event('task_started'), codex_response('function_call', call_id='x', name='read', arguments='{}'),
                codex_response('function_call_output', call_id='x', output='')]
        view = structured(parse(parse_codex_session, rows))[0]
        self.assertFalse(view['turn_ended'])
        self.assertTrue(view['tool_evidence_complete'])
        self.assertTrue(view['tools'][0]['result_observed'])
        self.assertFalse(view['complete'])

if __name__ == '__main__':
    unittest.main()
