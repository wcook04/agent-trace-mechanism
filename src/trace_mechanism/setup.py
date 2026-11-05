"""Inspect local histories and register only files the user explicitly selects."""
import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys

from . import codex_native
from .parser import parse_claude_session, parse_codex_session


def history_root(provider):
    if provider == 'codex':
        return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'sessions'
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'projects'


def history_roots(provider):
    active = history_root(provider)
    return (active, active.with_name('archived_sessions')) if provider == 'codex' else (active,)


def connection(manifest):
    from .mcp_server import load_manifest
    manifest = manifest.expanduser().resolve(strict=True)
    load_manifest(manifest)
    # Resolving a venv's Python symlink would select the base interpreter instead.
    return {'command': os.path.abspath(sys.executable), 'args': [
        '-m', 'trace_mechanism.mcp_server', '--manifest', str(manifest)]}


async def verify(manifest):
    """Exercise local stdio without a host, model call, or transcript output."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from .mcp_server import load_manifest
    entries = load_manifest(manifest.expanduser())
    if not entries:
        raise ValueError('Select at least one history before verifying a read.')
    config = connection(manifest)
    async with stdio_client(StdioServerParameters(**config)) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            listed = await client.list_tools()
            found = await client.call_tool('search_trace_threads', {'query': ''})
            if found.isError or found.structuredContent is None:
                raise ValueError('MCP session listing failed.')
            expected = {(e['provider'], e['session_id']) for e in entries}
            actual = {(e['provider'], e['session_id']) for e in found.structuredContent['items']}
            if actual != expected:
                raise ValueError('MCP session listing differs from the selected manifest.')
            for entry in entries:
                result = await client.call_tool('read_chat_context', {
                    'provider': entry['provider'], 'session_id': entry['session_id'],
                    'scope': 'full_thread_concise', 'limit': 1})
                if result.isError:
                    raise ValueError('A selected history could not be read. Run setup check on each selected file.')
    return {'ok': True, 'sessions_read': len(entries),
            'tools': sorted(tool.name for tool in listed.tools),
            'note': 'Local MCP handshake, listing and compact reads passed. No model was called. Host discovery still needs checking in a new chat.'}


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
                payload = row.get('payload')
                if not isinstance(payload, dict):
                    raise ValueError('Invalid Codex session metadata.')
                return {**payload, 'provider': 'codex'}
            if (isinstance(row, dict) and row.get('type') in ('user', 'assistant')
                    and isinstance(row.get('sessionId'), str) and row['sessionId']):
                return {'provider': 'claude', 'id': row['sessionId'],
                        'timestamp': row.get('timestamp'), 'cli_version': row.get('version')}
    return {}


def inspect(path):
    path = path.expanduser().resolve(strict=True)
    meta = metadata(path)
    if meta.get('provider') == 'claude':
        turns = parse_claude_session(path)
        return {'path': str(path), 'provider': 'claude', 'session_id': meta['id'],
                'cli_version': meta.get('cli_version'),
                'coverage': 'conversation' if turns else 'unsupported',
                'turns': len(turns), 'tool_calls': sum(len(t.tool_events) for t in turns),
                'note': 'Compact/detailed conversation reads; native item queries are Codex-only.'}
    try:
        snapshot = codex_native.load_rollout(path)
    except ValueError as exc:
        if str(exc) != 'No exact session identity recorded; supply session_id.':
            raise
        snapshot = {'items': [], 'diagnostics': {'missing_session_identity': True}}
    kinds = Counter(item['kind'] for item in snapshot['items'])
    native = bool(kinds)
    legacy = not native and bool(parse_codex_session(path))
    return {'path': str(path), 'provider': 'codex', 'session_id': meta.get('id'),
            'cli_version': meta.get('cli_version'),
            'coverage': 'native' if native else 'legacy_conversation' if legacy else 'unsupported',
            'native_items': len(snapshot['items']), 'item_kinds': dict(kinds),
            'diagnostics': snapshot['diagnostics']}


def register(paths, manifest):
    reports = [inspect(path) for path in paths]
    ids = [(report['provider'], report['session_id']) for report in reports]
    if any(not isinstance(sid, str) or not sid for _, sid in ids):
        raise ValueError('Each selected file needs a recorded session identity.')
    if len(ids) != len(set(ids)):
        raise ValueError('Select each session once.')
    if any(report['coverage'] == 'unsupported' for report in reports):
        raise ValueError('A selected file has no supported records; run check on it first.')
    entries = []
    for report in reports:
        meta = metadata(Path(report['path']))
        source = meta.get('source', {})
        subagent = source.get('subagent') if isinstance(source, dict) else None
        spawn = subagent.get('thread_spawn') if isinstance(subagent, dict) else None
        parent = (spawn.get('parent_thread_id') if isinstance(spawn, dict) else None) or meta.get('parent_thread_id')
        entry = {'provider': report['provider'], 'session_id': report['session_id'],
                 'title': Path(report['path']).stem, 'path': report['path']}
        if entry['provider'] == 'codex' and ('codex', parent) in ids:
            entry['parent_session_id'] = parent
        entries.append(entry)
    parents = {entry['session_id']: entry.get('parent_session_id')
               for entry in entries if entry['provider'] == 'codex'}
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
    listing.add_argument('--provider', choices=('codex', 'claude'), default='codex')
    listing.add_argument('--root', type=Path)
    listing.add_argument('--limit', type=int, default=10)
    check = sub.add_parser('check', help='Report supported native items or legacy conversation coverage')
    check.add_argument('path', type=Path)
    registration = sub.add_parser('register', help='Create a new manifest for explicitly selected files')
    registration.add_argument('paths', type=Path, nargs='+')
    registration.add_argument('--manifest', type=Path, required=True)
    for name, help_text in [('connection', 'Print absolute stdio command/args for this environment'),
                            ('verify', 'Test local MCP listing and reads without printing transcript text')]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'list':
            if not 1 <= args.limit <= 100:
                raise ValueError('--limit must be between 1 and 100.')
            roots = (args.root.expanduser().resolve(strict=True),) if args.root else history_roots(args.provider)
            dated = []
            for path in (file for root in roots for file in root.rglob('*.jsonl')):
                try:
                    dated.append((path.stat().st_mtime, path))
                except OSError:
                    continue  # A removed/inaccessible file must not hide readable histories.
            files = [path for _, path in sorted(dated, reverse=True)]
            result = []
            for path in files[:args.limit]:
                try:
                    meta = metadata(path)
                    result.append({'path': str(path), 'provider': meta.get('provider'), 'session_id': meta.get('id'),
                                   'timestamp': meta.get('timestamp'), 'cli_version': meta.get('cli_version')})
                except (OSError, ValueError) as exc:
                    result.append({'path': str(path), 'error': str(exc)})
        elif args.action == 'check':
            result = inspect(args.path)
        elif args.action == 'connection':
            result = connection(args.manifest)
        elif args.action == 'verify':
            try:
                result = asyncio.run(asyncio.wait_for(verify(args.manifest), timeout=60))
            except ImportError:
                raise
            except asyncio.TimeoutError:
                raise ValueError('MCP verification timed out after 60 seconds. Check the interpreter and selected files.') from None
            except Exception as exc:
                # MCP transports may wrap failures in an exception group. Do not
                # print its nested server output, which may include source text.
                raise ValueError(f'MCP verification failed ({type(exc).__name__}). Run setup check on the selected files and check the configured interpreter.') from None
        else:
            result = register(args.paths, args.manifest)
        print(json.dumps(result, indent=2))
    except ImportError:
        parser.exit(2, 'Agent Trace setup: install the MCP extra with python -m pip install ".[mcp]" from the checkout.\n')
    except (OSError, ValueError, TypeError, AttributeError, asyncio.TimeoutError) as exc:
        parser.exit(2, f'Agent Trace setup: {exc}\n')


if __name__ == '__main__':
    main()
