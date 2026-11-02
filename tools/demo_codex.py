#!/usr/bin/env python3
"""Replay a selected real Codex recording through the public stdio MCP server."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples/codex-retrieval'


async def demo():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / 'source.jsonl'
        source.write_bytes((EXAMPLE / 'source-before.jsonl').read_bytes())
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps([{'provider': 'codex', 'session_id': 'repair-cafe',
                                        'title': 'Repair cafe', 'path': source.name}]))
        params = StdioServerParameters(command=sys.executable, args=[
            '-m', 'trace_mechanism.mcp_server', '--manifest', str(manifest)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()

                async def call(name, **arguments):
                    result = await client.call_tool(name, arguments)
                    if result.isError:
                        raise RuntimeError(result.content)
                    data = dict(result.structuredContent or {})
                    if name in ('read_chat_context', 'read_trace_page'):
                        data['text'] = ''.join(block.text for block in result.content if block.type == 'text')
                    return data

                found = await call('search_trace_threads', query='repair cafe')
                selection = {key: found['items'][0][key] for key in ('provider', 'session_id')}
                before = await call('read_chat_context', **selection)
                source.write_bytes((EXAMPLE / 'source-after.jsonl').read_bytes())
                after = await call('read_chat_context', **selection)
                old = await call('read_trace_page', sha256=before['sha256'])
                detail = await call('read_chat_context', **selection, scope='full_thread')
                assert before['sha256'] != after['sha256']
                assert old['text'] == before['text']
                assert '10:30' in after['text'] and '10:30' not in before['text']
                results = [json.loads(line.split('): ', 1)[1]) for line in detail['text'].splitlines()
                           if line.startswith('RESULT ')]
                assert any('"exit_code":0' in text and '"output":"21\\n"' in text for text in results)
                for label, response in [('Before', before), ('After', after)]:
                    final = [line for line in response['text'].splitlines() if line.startswith('ASSISTANT:')][-1]
                    print(label + ': ' + json.loads(final.removeprefix('ASSISTANT: ')))
                print('Earlier snapshot unchanged: true')
                print('Detailed view includes the recorded Python call and output.')


if __name__ == '__main__':
    asyncio.run(demo())
