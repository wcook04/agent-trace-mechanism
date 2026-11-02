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
                                     {'search_trace_threads', 'read_chat_context', 'read_trace_page',
                                      'search_trace_items', 'read_trace_item', 'read_trace_changes'})

                    async def call(name, args):
                        result = await client.call_tool(name, args)
                        self.assertFalse(result.isError, result.content)
                        data = dict(result.structuredContent)
                        if name in ('read_chat_context', 'read_trace_page'):
                            self.assertNotIn('text', data)
                            data['text'] = result.content[0].text
                        return data

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


    async def test_native_field_transport_retains_exact_value_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'native.jsonl'
            output = 'original native output\n' * 400
            rows = [
                {'type': 'session_meta', 'payload': {'id': 'native-session'}},
                {'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': 'native-session',
                    'turn_id': 'turn', 'item': {'type': 'CommandExecution', 'id': 'exec-item',
                    'command': ['pytest'], 'exit_code': 1, 'aggregated_output': output}}}]
            write_records(source, rows, 'w')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps([{'provider': 'codex', 'session_id': 'native-session',
                                             'title': 'Native transport regression', 'path': source.name}]))
            params = StdioServerParameters(command=sys.executable, args=[
                '-m', 'trace_mechanism.mcp_server', '--manifest', str(manifest)])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    result = await client.call_tool('read_chat_context', {
                        'provider': 'codex', 'session_id': 'native-session', 'scope': 'full_thread'})
                    self.assertFalse(result.isError, result.content)
                    row = json.loads(next(x.removeprefix('Native item: ') for x in result.content[0].text.splitlines()
                                          if x.startswith('Native item: ')))
                    ref = row['aggregated_output']['evidence_ref']
                    source.unlink()
                    exact = await client.call_tool('read_trace_item', {
                        'provider': 'codex', 'session_id': ref['session_id'], 'item_id': ref['item_id'],
                        'snapshot_sha256': ref['snapshot_sha256'], 'field': ref['field'], 'limit': 48000})
                    self.assertFalse(exact.isError, exact.content)
                    self.assertEqual(json.loads(exact.content[0].text), output)
                    self.assertNotIn('payload', exact.structuredContent)
                    self.assertNotIn('payload_json', exact.structuredContent)

if __name__ == '__main__':
    unittest.main()
