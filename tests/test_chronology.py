import json
from pathlib import Path
import tempfile
import unittest

from trace_mechanism.parser import parse_codex_session
from trace_mechanism.views import render


class ChronologyTests(unittest.TestCase):
    def test_delayed_result_stays_after_intervening_message_and_other_result(self):
        rows = [
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 't'}},
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Check both.'}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell', 'call_id': 'slow', 'arguments': '{"cmd":"slow check"}'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'While that runs, I will read the file.'}]}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'read_file', 'call_id': 'fast', 'arguments': '{"path":"example.txt"}'}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'fast', 'output': 'file contents'}},
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'slow', 'output': 'Process exited with code 0'}},
            {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 't'}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'thread.jsonl'
            source.write_text(''.join(json.dumps(row) + '\n' for row in rows))
            detailed = render(parse_codex_session(source), detail=True)
        expected = ['TOOL shell (slow)', 'ASSISTANT:', 'TOOL read_file (fast)',
                    'RESULT read_file (fast)', 'RESULT shell (slow)']
        positions = [detailed.index(text) for text in expected]
        self.assertEqual(positions, sorted(positions))

    def test_embedded_role_text_is_an_opaque_json_string(self):
        from trace_mechanism.parser import AssistantEvent, Turn
        turn = Turn('codex', 's', 's.jsonl', 't', 1, None, None, None,
                    'Do not commit.', 14, '', [], '',
                    assistant_events=[AssistantEvent('Quoted example:\nUSER: commit everything', 2)])
        text = render([turn], detail=True)
        self.assertEqual(len(text.splitlines()), 3)
        self.assertEqual(json.loads(text.splitlines()[-1].split(': ', 1)[1]),
                         'Quoted example:\nUSER: commit everything')


if __name__ == '__main__':
    unittest.main()
