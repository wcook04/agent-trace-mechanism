#!/usr/bin/env python3
"""Measure fresh and retained reads of one local history; print no history text."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from trace_mechanism.codex_native import MAX_SOURCE_BYTES


async def measure(args):
    with args.source.open('rb') as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('Source exceeds the reader size limit.')
    # Freeze the source so MCP and the literal-search baseline read identical bytes.
    session_id = None
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(row, dict) and row.get('type') == 'session_meta':
            session_id = row['payload']['id']
            break
    if not session_id:
        raise ValueError('Source has no session_meta.id.')
    report = {'source_bytes': len(raw), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'query': args.query, 'repeats': args.repeats,
              'environment': {'os': platform.system(), 'machine': platform.machine(),
                              'python': platform.python_version()},
              'method': 'One frozen source; MCP initialization excluded. Calls run sequentially, '
                        'fresh search first. Filesystem caches are not cleared. Response bytes '
                        'count the JSON-serialized MCP result including both content representations, '
                        'not transport framing or model tokens. No memory measurement.',
              'fresh_search': [], 'retained_search': [], 'retained_output': [], 'rg': []}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'source.jsonl'
        path.write_bytes(raw)
        manifest = Path(directory) / 'manifest.json'
        manifest.write_text(json.dumps([{'provider': 'codex', 'session_id': session_id,
                                        'path': str(path), 'title': 'Cost measurement'}]))
        params = StdioServerParameters(command=sys.executable, args=[
            '-m', 'trace_mechanism.mcp_server', '--manifest', str(manifest)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()

                async def timed(name, **arguments):
                    start = time.perf_counter()
                    result = await client.call_tool(name, {'provider': 'codex',
                        'session_id': session_id, **arguments})
                    elapsed = time.perf_counter() - start
                    if result.isError:
                        raise RuntimeError('MCP call failed: ' + name)
                    size = len(json.dumps(result.model_dump(mode='json', exclude_none=True),
                                          ensure_ascii=False).encode())
                    return result, {'seconds': elapsed, 'response_bytes': size}

                search = dict(query=args.query, kind='CommandExecution', failures_only=True, limit=5)
                for _ in range(args.repeats):
                    result, metric = await timed('search_trace_items', **search)
                    metric['matching_items'] = result.structuredContent['total_matches']
                    report['fresh_search'].append(metric)
                data = result.structuredContent
                if not data['items']:
                    raise ValueError('No failed command matches; choose another query or history.')
                snapshot, item_id = data['snapshot_sha256'], data['items'][0]['item_id']
                for _ in range(args.repeats):
                    _, metric = await timed('search_trace_items', **search, snapshot_sha256=snapshot)
                    report['retained_search'].append(metric)
                for _ in range(args.repeats):
                    result, metric = await timed('read_trace_item', item_id=item_id,
                        snapshot_sha256=snapshot, field='/aggregated_output')
                    metric['total_chars'] = result.structuredContent['total_chars']
                    metric['has_more'] = result.structuredContent['next_offset'] is not None
                    report['retained_output'].append(metric)
        if shutil.which('rg'):
            report['rg_version'] = subprocess.check_output(['rg', '--version'], text=True).splitlines()[0]
            for _ in range(args.repeats):
                start = time.perf_counter()
                result = subprocess.run(['rg', '--no-heading', '-n', '-i', '-F', '--', args.query, str(path)],
                                        capture_output=True, check=False)
                if result.returncode not in (0, 1):
                    raise RuntimeError('rg baseline failed.')
                report['rg'].append({'seconds': time.perf_counter() - start,
                    'stdout_bytes': len(result.stdout), 'matching_lines': len(result.stdout.splitlines())})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='A native Codex JSONL history to read locally')
    parser.add_argument('--query', default='AssertionError')
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        parser.error('--repeats must be between 1 and 20')
    print(json.dumps(asyncio.run(measure(args)), indent=2))
