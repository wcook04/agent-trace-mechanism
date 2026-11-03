#!/usr/bin/env python3
"""Read Claude's real review and repeat its selected Codex reads through MCP."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DIRECTORY = Path(__file__).resolve().parents[1] / 'examples/cross-provider'


async def main():
    source = DIRECTORY / 'claude-review.jsonl'
    provenance = json.loads((DIRECTORY / 'provenance.json').read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == provenance['selected_sha256']
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    selection = {'provider': 'claude', 'session_id': provenance['session_id']}
    params = StdioServerParameters(command=sys.executable, args=[
        '-m', 'trace_mechanism.mcp_server', '--manifest', str(DIRECTORY / 'manifest.json')])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()

            async def call(name, args):
                result = await client.call_tool(name, args)
                assert not result.isError, result.content
                return result

            found = await call('search_trace_threads', {'query': ''})
            assert {r['provider'] for r in found.structuredContent['items']} == {'codex', 'claude'}
            compact = await call('read_chat_context', selection)
            text = compact.structuredContent['text']
            assert text == compact.content[0].text
            assert 'Agent Trace text now comes through in full.' in text
            assert 'RESULT mcp__agent-trace__read_trace_item' not in text
            print('Read Claude\'s final review from its compact conversation.')

            detail = await call('read_chat_context', {**selection, 'scope': 'full_thread', 'limit': 3000})
            page, chunks = detail.structuredContent, [detail.structuredContent['text']]
            while page['next_offset'] is not None:
                result = await call('read_trace_page', {'sha256': page['text_sha256'],
                                    'offset': page['next_offset'], 'limit': 3000})
                page = result.structuredContent
                assert page['text'] == result.content[0].text
                chunks.append(page['text'])
            assert 'RESULT mcp__agent-trace__read_trace_item' in ''.join(chunks)
            print('Paged the detailed conversation, including its actual MCP calls and results.')

            calls = [block for row in rows for block in row['message']['content']
                     if isinstance(block, dict) and block.get('type') == 'tool_use'
                     and block.get('name') == 'mcp__agent-trace__read_trace_item']
            root = json.loads((DIRECTORY / 'manifest.json').read_text())[0]
            captured = await call('search_trace_items', {'provider': 'codex',
                'session_id': root['session_id'], 'include_children': True})
            for recorded in calls:
                args = {**recorded['input'], 'snapshot_sha256': captured.structuredContent['snapshot_sha256']}
                result = await call('read_trace_item', args)
                assert result.structuredContent['payload_json'] == result.content[0].text
                # Original Claude results contain the host-visible structured object.
                output = next(block for row in rows for block in row['message']['content']
                              if isinstance(block, dict) and block.get('type') == 'tool_result'
                              and block.get('tool_use_id') == recorded['id'])
                content = output['content']
                original = json.loads(content if isinstance(content, str) else
                                      ''.join(b['text'] for b in content if b['type'] == 'text'))
                assert result.structuredContent['payload_json'] == original['payload_json']
            assert len(calls) == 3
            print('Repeated Claude\'s three Codex item reads: both worker answers and a command-output page match.')
    print('All records are from the release review. No model calls or historical commands were executed.')


if __name__ == '__main__':
    asyncio.run(main())
