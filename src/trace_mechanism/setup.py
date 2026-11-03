"""Inspect local histories and register only files the user explicitly selects."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

from . import codex_native
from .parser import parse_codex_session


def metadata(path):
    with path.open('rb') as stream:
        for _ in range(100):
            line = stream.readline(codex_native.MAX_RECORD_BYTES + 1)
            if not line:
                break
            if len(line) > codex_native.MAX_RECORD_BYTES:
                raise ValueError('Metadata record exceeds the reader limit.')
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(row, dict) and row.get('type') == 'session_meta':
                return row.get('payload', {})
    return {}


def inspect(path):
    path = path.expanduser().resolve(strict=True)
    meta = metadata(path)
    try:
        snapshot = codex_native.load_rollout(path)
    except ValueError as exc:
        if str(exc) != 'No exact session identity recorded; supply session_id.':
            raise
        snapshot = {'items': [], 'diagnostics': {'missing_session_identity': True}}
    kinds = Counter(item['kind'] for item in snapshot['items'])
    native = bool(kinds)
    legacy = not native and bool(parse_codex_session(path))
    return {'path': str(path), 'session_id': meta.get('id'),
            'cli_version': meta.get('cli_version'),
            'coverage': 'native' if native else 'legacy_conversation' if legacy else 'unsupported',
            'native_items': len(snapshot['items']), 'item_kinds': dict(kinds),
            'diagnostics': snapshot['diagnostics']}


def register(paths, manifest):
    reports = [inspect(path) for path in paths]
    ids = [report['session_id'] for report in reports]
    if any(not isinstance(sid, str) or not sid for sid in ids):
        raise ValueError('Each selected file needs a recorded session_meta.id.')
    if len(ids) != len(set(ids)):
        raise ValueError('Select each session once.')
    if any(report['coverage'] == 'unsupported' for report in reports):
        raise ValueError('A selected file has no supported records; run check on it first.')
    entries = []
    for report in reports:
        meta = metadata(Path(report['path']))
        source = meta.get('source', {})
        parent = (source.get('subagent', {}).get('thread_spawn', {}).get('parent_thread_id')
                  if isinstance(source, dict) else None) or meta.get('parent_thread_id')
        entry = {'provider': 'codex', 'session_id': report['session_id'],
                 'title': Path(report['path']).stem, 'path': report['path']}
        if parent in ids:
            entry['parent_session_id'] = parent
        entries.append(entry)
    parents = {entry['session_id']: entry.get('parent_session_id') for entry in entries}
    for sid in parents:
        seen, cursor = set(), sid
        while cursor:
            if cursor in seen:
                raise ValueError('Selected session parent relationships contain a cycle.')
            seen.add(cursor)
            cursor = parents.get(cursor)
    manifest = manifest.expanduser().absolute()
    # Never replace an existing file or follow an existing destination symlink.
    descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(entries, stream, indent=2)
        stream.write('\n')
    return {'manifest': str(manifest), 'registered': reports,
            'note': 'Only these files are registered. No host configuration was changed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('list', help='List recent session metadata locally; does not register files')
    listing.add_argument('--root', type=Path, default=Path.home() / '.codex/sessions')
    listing.add_argument('--limit', type=int, default=10)
    check = sub.add_parser('check', help='Report supported native items or legacy conversation coverage')
    check.add_argument('path', type=Path)
    registration = sub.add_parser('register', help='Create a new manifest for explicitly selected files')
    registration.add_argument('paths', type=Path, nargs='+')
    registration.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'list':
            if not 1 <= args.limit <= 100:
                raise ValueError('--limit must be between 1 and 100.')
            root = args.root.expanduser().resolve(strict=True)
            files = sorted(root.rglob('*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)
            result = []
            for path in files[:args.limit]:
                try:
                    meta = metadata(path)
                    result.append({'path': str(path), 'session_id': meta.get('id'),
                                   'timestamp': meta.get('timestamp'), 'cli_version': meta.get('cli_version')})
                except (OSError, ValueError) as exc:
                    result.append({'path': str(path), 'error': str(exc)})
        elif args.action == 'check':
            result = inspect(args.path)
        else:
            result = register(args.paths, args.manifest)
        print(json.dumps(result, indent=2))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        parser.exit(2, f'Agent Trace setup: {exc}\n')


if __name__ == '__main__':
    main()
