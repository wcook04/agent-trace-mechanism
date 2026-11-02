"""Parse one explicitly named JSONL file and print a small normalized view."""
import argparse
import json
from pathlib import Path
from .parser import parse_claude_session, parse_codex_session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=('codex', 'claude'))
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    turns = (parse_codex_session if args.provider == 'codex' else parse_claude_session)(args.file)
    result = []
    for turn in turns:
        result.append({'prompt': turn.prompt_text, 'assistant': turn.assistant_text,
                       'complete': turn.is_complete, 'partial_reason': turn.partial_reason,
                       'tools': [{'name': event.name, 'call_id': event.tool_call_id,
                                  'input': event.input, 'output': event.output_text,
                                  'error': event.is_error} for event in turn.tool_events]})
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
