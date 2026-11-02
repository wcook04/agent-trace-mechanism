"""Read one explicitly named JSONL file; emit a selected demonstration view."""
import argparse
import json
from pathlib import Path
from .parser import parse_claude_session, parse_codex_session
from .views import render, structured


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=('codex', 'claude'))
    parser.add_argument('file', type=Path)
    parser.add_argument('--view', choices=('json', 'compact', 'detailed'), default='json')
    args = parser.parse_args()
    turns = (parse_codex_session if args.provider == 'codex' else parse_claude_session)(args.file)
    if args.view == 'json':
        print(json.dumps(structured(turns), indent=2, ensure_ascii=False))
    else:
        print(render(turns, detail=args.view == 'detailed'))


if __name__ == '__main__':
    main()
