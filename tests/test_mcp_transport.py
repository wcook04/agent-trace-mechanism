"""Real stdio MCP integration against explicit synthetic files."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from trace_mechanism.replay import records

HAS_MCP = importlib.util.find_spec('mcp') is not None
if HAS_MCP:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client


def write_records(path, rows, mode):
    with path.open(mode, encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row) + '\n')


@unittest.skipUnless(HAS_MCP, 'install the mcp extra for transport integration')
class MCPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_search_read_refresh_and_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entries, updates = [], {}
            for provider in ('codex', 'claude'):
                path = root / (provider + '.jsonl')
                initial, later, _ = records(provider)
                write_records(path, initial, 'w')
                updates[provider] = (path, later)
                entries.append({'provider': provider, 'session_id': 'test-' + provider,
                                'title': provider + ' investigation', 'path': path.name})
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(entries), encoding='utf-8')
            params = StdioServerParameters(command=sys.executable, args=[
                '-m', 'trace_mechanism.mcp_server', '--manifest', str(manifest)])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    listed = await client.list_tools()
                    self.assertEqual({t.name for t in listed.tools},
                                     {'search_trace_threads', 'read_chat_context', 'read_trace_page'})

                    async def call(name, args):
                        result = await client.call_tool(name, args)
                        self.assertFalse(result.isError, result.content)
                        return result.structuredContent

                    for provider in ('codex', 'claude'):
                        found = await call('search_trace_threads', {'query': provider + ' investigation'})
                        self.assertEqual(found['items'][0]['session_id'], 'test-' + provider)
                        self.assertEqual(found['items'][0]['provider'], provider)
                        selection = {'provider': provider, 'session_id': 'test-' + provider}
                        compact = await call('read_chat_context', selection)
                        self.assertIn('[omitted in compact view]', compact['text'])
                        detail = await call('read_chat_context', {**selection, 'scope': 'full_thread', 'limit': 10})
                        self.assertIsNotNone(detail['next_offset'])
                        old = await call('read_trace_page', {'sha256': detail['sha256'], 'offset': detail['next_offset']})
                        path, later = updates[provider]
                        write_records(path, later, 'a')
                        newer = await call('read_chat_context', {**selection, 'scope': 'full_thread'})
                        self.assertNotEqual(newer['sha256'], detail['sha256'])
                        self.assertRegex(newer['text'], r'RESULT .+ \(c1\): "ok"')
                        old_again = await call('read_trace_page', {'sha256': detail['sha256'], 'offset': detail['next_offset']})
                        self.assertEqual(old, old_again)
                        self.assertNotRegex(detail['text'] + old['text'], r'RESULT .+ \(c1\): "ok"')


if __name__ == '__main__':
    unittest.main()
