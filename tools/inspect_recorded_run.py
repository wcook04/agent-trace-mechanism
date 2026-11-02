#!/usr/bin/env python3
"""Retrieve a real failure, fixture correction and retry through the MCP server."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'examples/validation-history.jsonl'


async def inspect():
    provenance = json.loads(SOURCE.with_name('validation-history-provenance.json').read_text())
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != provenance['selected_file_sha256']:
        raise RuntimeError('Selected records differ from their provenance receipt.')
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines()]
    session_id = rows[0]['payload']['id']
    originals = {row['payload']['item']['id']: row['payload']['item'] for row in rows[1:]}
    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory) / 'manifest.json'
        manifest.write_text(json.dumps([{
            'provider': 'codex', 'session_id': session_id,
            'title': 'Agent Trace validation history', 'path': str(SOURCE),
        }]))
        params = StdioServerParameters(command=sys.executable, args=[
            '-m', 'trace_mechanism.mcp_server', '--manifest', str(manifest)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()

                async def call(name, **arguments):
                    result = await client.call_tool(name, {'provider': 'codex',
                        'session_id': session_id, **arguments})
                    if result.isError:
                        raise RuntimeError(result.content)
                    return result

                failed = await call('search_trace_items', query='AssertionError',
                                    kind='CommandExecution', failures_only=True)
                data = failed.structuredContent
                assert data['total_matches'] == 1
                snapshot = data['snapshot_sha256']
                found = await call('search_trace_items', query='parser.test.mjs',
                                   kind='CommandExecution', snapshot_sha256=snapshot)
                assert found.structuredContent['total_matches'] == 5
                entries = []
                for hit in found.structuredContent['items']:
                    result = await call('read_trace_item', item_id=hit['item_id'],
                                        snapshot_sha256=snapshot)
                    assert result.structuredContent['next_offset'] is None
                    entry = json.loads(''.join(p.text for p in result.content if p.type == 'text'))
                    for field in ('command', 'aggregated_output', 'exit_code'):
                        assert entry['item'][field] == originals[hit['item_id']][field]
                    entries.append(entry)

    entries.sort(key=lambda row: row['first_record'])
    early, failure, dry_run, applied, retry = [row['item'] for row in entries]
    assert 'ℹ pass 60' in early['aggregated_output']
    assert failure['exit_code'] == 1 and 'ℹ fail 1' in failure['aggregated_output']
    assert 'capsule validation uses the observed output of its own command' in failure['aggregated_output']
    assert 'OK [DRY RUN]' in dry_run['aggregated_output']
    assert 'OK [LIVE]' in applied['aggregated_output']
    assert 'JSON.stringify' in applied['aggregated_output']
    assert retry['exit_code'] == 0 and '| tail -10' in retry['command'][-1]
    assert 'ℹ pass 124' in retry['aggregated_output'] and 'ℹ fail 0' in retry['aggregated_output']
    print('Retrieved five original commands and outputs through MCP; all match the selected records.')
    for label, entry in zip(('Earlier run: 60 passed', 'Combined run: 123 passed, 1 failed',
                             'Fixture correction: dry run only', 'Fixture correction: applied',
                             'Combined retry: 124 passed, 0 failed'), entries):
        print(f"{label}\n  {entry['item_id']}")
    print('\nThe retry output reports success; its pipeline exit code alone would not prove it.')
    print('This checks recorded evidence. It does not run the historical commands or verify current app code.')


if __name__ == '__main__':
    asyncio.run(inspect())
