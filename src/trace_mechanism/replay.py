"""Append synthetic records to temporary files and explicitly refresh both parsers."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from .parser import parse_codex_session, parse_claude_session
from .views import structured


def records(provider):
    if provider == 'codex':
        initial = [
            {'type': 'session_meta', 'payload': {'id': 'synthetic-live'}},
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 't1'}},
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'Run the check.'}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell', 'call_id': 'c1', 'arguments': '{"cmd":"check"}'}},
        ]
        later = [
            {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'c1', 'output': 'ok'}},
            {'type': 'event_msg', 'timestamp': '2026-01-01T00:00:00Z', 'payload': {'type': 'task_complete', 'last_agent_message': 'Done.'}},
        ]
        return initial, later, parse_codex_session
    if provider == 'claude':
        initial = [
            {'type': 'user', 'sessionId': 'synthetic-live', 'message': {'content': 'Run the check.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': 'c1', 'name': 'Bash', 'input': {'command': 'check'}}], 'stop_reason': 'tool_use'}},
        ]
        later = [
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'c1', 'content': 'ok'}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Done.'}], 'stop_reason': 'end_turn'}},
        ]
        return initial, later, parse_claude_session
    raise ValueError('Unknown provider')


def replay(provider, path):
    initial, later, parse = records(provider)
    with path.open('w') as f:
        for item in initial:
            f.write(json.dumps(item) + '\n')
    before = structured(parse(path))
    with path.open('a') as f:
        for item in later:
            f.write(json.dumps(item) + '\n')
    after = structured(parse(path))
    return {'provider': provider, 'before': before, 'after': after}


def main():
    with TemporaryDirectory() as directory:
        for provider in ('codex', 'claude'):
            print(json.dumps(replay(provider, Path(directory) / (provider + '.jsonl')), indent=2))


if __name__ == '__main__':
    main()
