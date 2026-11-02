#!/usr/bin/env python3
"""Capture current MCP responses for an existing recorded development command."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'examples/native-command.jsonl'
TARGET = ROOT / 'examples/native-command-response.json'


async def capture():
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines()]
    session_id = rows[0]['payload']['id']
    source_item = rows[1]['payload']['item']
    calls = []
    with tempfile.TemporaryDirectory() as directory:
        manifest = Path(directory) / 'manifest.json'
        manifest.write_text(json.dumps([{
            'provider': 'codex', 'session_id': session_id,
            'title': 'Agent Trace development: chronology tests', 'path': str(SOURCE),
        }]))
        params = StdioServerParameters(command=sys.executable, args=[
            '-m', 'trace_mechanism.mcp_server', '--manifest', str(manifest)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()

                async def call(name, **arguments):
                    result = await client.call_tool(name, arguments)
                    if result.isError:
                        raise RuntimeError(result.content)
                    calls.append({'tool': name, 'arguments': arguments, 'result': {
                        'content': [part.model_dump(mode='json', exclude_none=True)
                                    for part in result.content],
                        'structuredContent': result.structuredContent,
                    }})
                    return result

                found = await call('search_trace_items', provider='codex', session_id=session_id,
                                   query='Ran 2 tests', kind='CommandExecution', limit=1)
                data = found.structuredContent
                assert data['total_matches'] == 1
                hit = data['items'][0]
                assert hit['item_id'] == source_item['id'] and hit['status'] == 'completed'
                result = await call('read_trace_item', provider='codex', session_id=session_id,
                                    item_id=hit['item_id'], snapshot_sha256=data['snapshot_sha256'],
                                    field='/aggregated_output')
                text = ''.join(part.text for part in result.content if part.type == 'text')
                assert json.loads(text) == source_item['aggregated_output']
    return {'source': 'native-command.jsonl', 'selection': (
        'Two selected records from existing Agent Trace development on 2 November 2026. '
        'Session metadata was reduced and the workspace path replaced with <public-repo>. '
        'Command, output, IDs and timestamps were retained. This is not the entire chat. '
        'Calls below are rerun against the current public MCP server; the recorded command is not executed.'),
        'calls': calls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if the saved responses differ')
    args = parser.parse_args()
    encoded = json.dumps(asyncio.run(capture()), indent=2, ensure_ascii=False) + '\n'
    if args.check:
        if not TARGET.is_file() or TARGET.read_text() != encoded:
            raise SystemExit('Native MCP response capture differs; run tools/record_native_contract.py and inspect it.')
        print('Native search and field retrieval match the recorded MCP contract.')
    else:
        TARGET.write_text(encoded)
        print('Updated examples/native-command-response.json')


if __name__ == '__main__':
    main()
