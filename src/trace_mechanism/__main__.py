"""Read one explicitly named JSONL file; query native items or render a selected view."""
import argparse
import json
from pathlib import Path
from .parser import parse_claude_session, parse_codex_session
from .views import render, structured
from . import codex_native as native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=('codex', 'claude'))
    parser.add_argument('file', type=Path)
    parser.add_argument('--view', choices=('json', 'compact', 'detailed'), default='json')
    parser.add_argument('--query', help='Search full native item content, including outputs and diffs')
    parser.add_argument('--kind', default='', help='Exact native kind, e.g. CommandExecution or FileChange')
    parser.add_argument('--failures', action='store_true', help='Select recorded nonzero exits or failed statuses')
    parser.add_argument('--item', help='Read one exact native item ID')
    parser.add_argument('--offset', type=int, default=0, help='Native item character offset or search result offset')
    parser.add_argument('--limit', type=int, help='Native item page size (default 24000) or search count (default 20)')
    parser.add_argument('--field', default='', help='JSON Pointer within the selected native item')
    parser.add_argument('--since', type=Path, help='Compare with an earlier native JSONL source snapshot')
    args = parser.parse_args()
    operations = [bool(args.item), bool(args.since),
                  args.query is not None or bool(args.kind) or args.failures]
    if sum(operations) > 1:
        parser.error('Choose one operation: item read, comparison, or search.')
    if args.field and not args.item:
        parser.error('--field requires --item')
    snapshot = native.load_rollout(args.file) if args.provider == 'codex' else None
    if snapshot and snapshot['items']:
        if args.item:
            result = native.read_item(snapshot, args.item, offset=args.offset, limit=24000 if args.limit is None else args.limit, field=args.field)
        elif args.since:
            result = native.diff_snapshots(native.load_rollout(args.since), snapshot)
        elif args.query is not None or args.kind or args.failures:
            result = native.search(snapshot, args.query or '', [args.kind] if args.kind else None, args.failures,
                                   limit=20 if args.limit is None else args.limit, offset=args.offset)
        elif args.view != 'json':
            print(native.render(snapshot, detail=args.view == 'detailed'), end='')
            return
        else:
            result = snapshot
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if args.item or args.since or args.query is not None or args.kind or args.failures:
        parser.error('Native queries require a file containing Codex native items.')
    turns = (parse_codex_session if args.provider == 'codex' else parse_claude_session)(args.file)
    if args.view == 'json':
        print(json.dumps(structured(turns), indent=2, ensure_ascii=False))
    else:
        print(render(turns, detail=args.view == 'detailed'))


if __name__ == '__main__':
    main()
