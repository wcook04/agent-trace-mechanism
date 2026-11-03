import json
from pathlib import Path
import pytest
from trace_mechanism.setup import inspect, register
from trace_mechanism.mcp_server import load_manifest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('options', [
    ['--item', 'some-id', '--query', 'test'],
    ['--since', 'old.jsonl', '--failures'],
    ['--item', 'some-id', '--since', 'old.jsonl'],
])
def test_cli_rejects_conflicting_operations(monkeypatch, options):
    from trace_mechanism.__main__ import main
    monkeypatch.setattr('sys.argv', ['trace_mechanism', 'codex', 'not-read.jsonl', *options])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_native_and_unsupported_are_distinct(tmp_path):
    native = inspect(ROOT / 'examples/native-command.jsonl')
    assert native['coverage'] == 'native' and native['native_items'] == 1
    assert inspect(ROOT / 'examples/codex.jsonl')['coverage'] == 'legacy_conversation'
    empty = tmp_path / 'empty.jsonl'
    empty.write_text('{}\n')
    assert inspect(empty)['coverage'] == 'unsupported'
    with pytest.raises(ValueError):
        register([empty], tmp_path / 'manifest.json')


def test_registration_preserves_existing_file_and_uses_absolute_source(tmp_path):
    manifest = tmp_path / 'manifest.json'
    register([ROOT / 'examples/native-command.jsonl'], manifest)
    original = manifest.read_bytes()
    assert Path(load_manifest(manifest)[0]['path']).is_absolute()
    assert manifest.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        register([ROOT / 'examples/native-command.jsonl'], manifest)
    assert manifest.read_bytes() == original


def test_registers_actual_provider_and_rejects_claude_identity_mismatch(tmp_path):
    from trace_mechanism.agent_tools import AgentTools
    source = ROOT / 'tests/fixtures/claude.jsonl'
    report = inspect(source)
    assert report['provider'] == 'claude' and report['coverage'] == 'conversation'
    assert report['tool_calls'] > 0
    manifest = tmp_path / 'mixed.json'
    register([ROOT / 'examples/native-command.jsonl', source], manifest)
    entries = load_manifest(manifest)
    assert [r['provider'] for r in entries] == ['codex', 'claude']
    api = AgentTools(entries)
    assert 'TOOL_RESULTS: [omitted' in api.read_chat_context('claude', report['session_id'])['text']
    entries[1]['session_id'] = 'wrong-id'
    with pytest.raises(ValueError, match='identity'):
        AgentTools(entries).read_chat_context('claude', 'wrong-id')


def test_string_subagent_metadata_is_valid_without_a_parent_edge(tmp_path):
    rows = [json.loads(line) for line in (ROOT / 'examples/native-command.jsonl').read_text().splitlines()]
    rows[0]['payload']['source'] = {'subagent': 'review'}
    source = tmp_path / 'review.jsonl'
    source.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
    manifest = tmp_path / 'manifest.json'
    register([source], manifest)
    assert 'parent_session_id' not in load_manifest(manifest)[0]


def test_listing_tolerates_a_broken_link(tmp_path, monkeypatch, capsys):
    from trace_mechanism.setup import main
    (tmp_path / 'broken.jsonl').symlink_to(tmp_path / 'missing')
    (tmp_path / 'valid.jsonl').write_bytes((ROOT / 'examples/native-command.jsonl').read_bytes())
    monkeypatch.setattr('sys.argv', ['setup', 'list', '--root', str(tmp_path)])
    main()
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_only_selected_parent_links_are_registered(tmp_path):
    sources = []
    for sid, parent in [('root', None), ('child', 'root'), ('unselected-parent-child', 'elsewhere')]:
        source = tmp_path / (sid + '.jsonl')
        rows = [json.loads(line) for line in (ROOT / 'examples/native-command.jsonl').read_text().splitlines()]
        rows[0]['payload']['id'] = sid
        rows[0]['payload']['parent_thread_id'] = parent
        rows[1]['payload']['thread_id'] = sid
        source.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
        sources.append(source)
    manifest = tmp_path / 'manifest.json'
    register(sources, manifest)
    entries = load_manifest(manifest)
    assert entries[1]['parent_session_id'] == 'root'
    assert 'parent_session_id' not in entries[2]


def test_selected_public_review_contains_no_other_record_families():
    directory = ROOT / 'examples/launch-review'
    entries = load_manifest(directory / 'manifest.json')
    assert len(entries) == 3
    assert sum(bool(entry.get('parent_edge_verified')) for entry in entries) == 2
    for entry in entries:
        text = Path(entry['path']).read_text()
        for excluded in ('/Users/', '/Volumes/', '<environment_context>', '<system', '<developer',
                         'developer_instructions', 'encrypted_content', 'raw_content'):
            assert excluded not in text
        rows = [json.loads(line) for line in text.splitlines()]
        assert set(rows[0]['payload']) <= {'id', 'timestamp', 'cli_version', 'parent_thread_id'}
        assert len(rows) == 3
        for row in rows[1:]:
            assert row['type'] == 'event_msg' and row['payload']['type'] == 'item_completed'
            assert row['payload']['item']['type'] in ('CommandExecution', 'AgentMessage')


def test_selected_claude_review_contains_only_declared_public_records():
    directory = ROOT / 'examples/cross-provider'
    entries = load_manifest(directory / 'manifest.json')
    assert [r['provider'] for r in entries].count('claude') == 1
    text = (directory / 'claude-review.jsonl').read_text()
    for excluded in ('/Users/', '/Volumes/', '<system', '<developer', 'requestId',
                     '"thinking"', '"signature"', '"toolUseResult"', '"mcpMeta"'):
        assert excluded not in text
    rows = [json.loads(line) for line in text.splitlines()]
    for row in rows:
        assert set(row) <= {'type', 'sessionId', 'uuid', 'timestamp', 'version', 'message'}
        assert row['type'] in ('user', 'assistant')
        assert set(row['message']) <= {'id', 'role', 'content', 'stop_reason'}
    report = inspect(directory / 'claude-review.jsonl')
    assert report['provider'] == 'claude' and report['tool_calls'] == 5 and report['turns'] == 1
