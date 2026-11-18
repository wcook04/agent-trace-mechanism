#!/usr/bin/env python3
"""Rebuild the copies in examples/reviewer-visibility from its recording.

Each copy is what Agent Trace gives a reviewing model for the same saved
conversation: with or without the opening note, compact or detailed, and with
the first assistant's thinking included. ``--check`` fails if a file differs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trace_mechanism.agent_tools import claude_text, visibility_fields, with_note  # noqa: E402

HERE = ROOT / 'examples/reviewer-visibility'
SESSION = 'reviewer-visibility-example'
COPIES = {  # name: (detailed, note, thinking)
    'compact': (False, False, False),
    'compact.note': (False, True, False),
    'detailed': (True, False, False),
    'detailed.note': (True, True, False),
    'detailed.note.thinking': (True, True, True),
}


def build():
    files = {}
    for name, (detail, note, thinking) in COPIES.items():
        found = []
        text, _, _, _ = claude_text(HERE / 'coding-session.jsonl', SESSION, detail, inventories=found, thinking=thinking)
        text, inventory = with_note(text, found, note=note)
        files[f'copies/{name}.txt'] = text + '\n'
        if name == 'compact.note':
            files['return-note.txt'] = visibility_fields(text, inventory)['return_note'] + '\n'
            files['inventory.json'] = json.dumps(inventory, indent=2, sort_keys=True) + '\n'
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    for name, text in build().items():
        path = HERE / name
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f'{name}  {hashlib.sha256(text.encode()).hexdigest()[:12]}  {len(text):,} chars')
    if stale:
        sys.exit('Stale: ' + ', '.join(stale) + '. Run tools/build_visibility_example.py')
    if args.check:
        print('Reviewer-visibility example verified.')


if __name__ == '__main__':
    main()
