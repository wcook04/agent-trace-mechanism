#!/usr/bin/env python3
"""Read selected real coordinator/worker records through a separate MCP server."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DIRECTORY = Path(__file__).resolve().parents[1] / 'examples/launch-review'


async def main():
    entries = json.loads((DIRECTORY / 'manifest.json').read_text())
    root = next(row for row in entries if 'parent_session_id' not in row)
    provenance = json.loads((DIRECTORY / 'provenance.json').read_text())
    for receipt in provenance['records']:
        assert hashlib.sha256((DIRECTORY / receipt['file']).read_bytes()).hexdigest() == receipt['selected_sha256']
    params = StdioServerParameters(command=sys.executable, args=[
        '-m', 'trace_mechanism.mcp_server', '--manifest', str(DIRECTORY / 'manifest.json')])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()

            async def call(name, **args):
                result = await client.call_tool(name, {'provider': 'codex', **args})
                if result.isError:
                    raise RuntimeError(result.content)
                return result

            parent = await call('search_trace_items', session_id=root['session_id'], kind='CommandExecution')
            tree = await call('search_trace_items', session_id=root['session_id'],
                              kind='CommandExecution', include_children=True)
            assert parent.structuredContent['total_matches'] == 1
            data = tree.structuredContent
            assert data['total_matches'] == 3
            assert {hit['session_id'] for hit in data['items']} == {row['session_id'] for row in entries}
            print('Coordinator only: 1 recorded command. With its two registered workers: 3.')
            for hit in data['items']:
                result = await call('read_trace_item', session_id=hit['session_id'], item_id=hit['item_id'],
                                    snapshot_sha256=data['snapshot_sha256'], field='/aggregated_output')
                assert result.structuredContent['next_offset'] is None
                output = json.loads(''.join(part.text for part in result.content if part.type == 'text'))
                entry = next(row for row in entries if row['session_id'] == hit['session_id'])
                rows = [json.loads(line) for line in (DIRECTORY / entry['path']).read_text().splitlines()]
                original = next(row['payload']['item'] for row in rows[1:]
                                if row['payload']['item']['id'] == hit['item_id'])
                assert output == original['aggregated_output']
                print(f"  {entry['title']}: exact output retrieved ({len(output)} characters)")
            findings = await call('search_trace_items', session_id=root['session_id'], kind='AgentMessage',
                                  query='working directory', include_children=True,
                                  snapshot_sha256=data['snapshot_sha256'])
            assert any(hit['session_id'] != root['session_id'] for hit in findings.structuredContent['items'])
            print('Found the worker\'s setup finding by searching its final answer.')
    print('Source: a fresh review of the public repository. These are selected records; no recorded commands ran.')


if __name__ == '__main__':
    asyncio.run(main())
