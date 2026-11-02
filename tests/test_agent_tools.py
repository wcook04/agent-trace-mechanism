"""Composition and availability contracts at the public agent boundary."""
import json
from pathlib import Path
import shutil

import pytest

from trace_mechanism.agent_tools import AgentTools
from trace_mechanism.mcp_server import load_manifest


def write_source(path, session, items, parent=None):
    meta = {'id': session}
    if parent:
        meta['parent_thread_id'] = parent
    rows = [{'type': 'session_meta', 'payload': meta}]
    rows += [{'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': session,
              'turn_id': 'turn', 'item': item}} for item in items]
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


def command(item_id, output='recorded output', code=0):
    return {'id': item_id, 'type': 'CommandExecution', 'command': ['pytest'],
            'status': 'completed', 'exit_code': code, 'aggregated_output': output}


def setup(tmp_path, children=False, reload=False):
    root = tmp_path / 'root.jsonl'
    write_source(root, 'root', [command('a')])
    entries = [{'provider': 'codex', 'session_id': 'root', 'title': 'Root', 'path': root.name}]
    child = tmp_path / 'child.jsonl'
    if children:
        write_source(child, 'child', [command('child-item')], 'root')
        entries.append({'provider': 'codex', 'session_id': 'child', 'title': 'Child', 'path': child.name,
                        'parent_session_id': 'root'})
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(entries))
    loader = (lambda: load_manifest(manifest)) if reload else None
    return AgentTools(load_manifest(manifest), entry_loader=loader), root, child, manifest


def test_supplied_manifest_identity_reaches_legacy_recording_fallback():
    source = Path(__file__).resolve().parents[1] / 'examples/codex-retrieval/source-before.jsonl'
    api = AgentTools([{'provider': 'codex', 'session_id': 'selected-recording',
                       'title': 'Selected recording', 'path': source}])
    context = api.read_chat_context('codex', 'selected-recording')
    assert context['context_format'] == 'legacy'
    assert 'ASSISTANT:' in context['text']
    assert context['snapshot_kind'] == 'text'
    assert 'snapshot_sha256' not in context and 'native_snapshot_sha256' not in context
    assert context['native_item_coverage']['native_sessions'] == []


def test_context_record_identity_composes_with_changes_and_text_identity_is_explicit(tmp_path):
    api, source, *_ = setup(tmp_path)
    before = api.read_chat_context('codex', 'root')
    detail = api.read_chat_context('codex', 'root', 'full_thread')
    assert before['snapshot_sha256'] == detail['snapshot_sha256']
    assert before['text_sha256'] != detail['text_sha256']
    assert before['sha256'] == before['text_sha256']
    write_source(source, 'root', [command('a', 'changed', 1), command('new')])
    delta = api.read_trace_changes('codex', 'root', before['snapshot_sha256'])
    assert [row['change'] for row in delta['items']] == ['added', 'updated']
    assert api.read_trace_changes('codex', 'root', before['native_snapshot_sha256'])['total_changes'] == 2
    with pytest.raises(ValueError, match='text_sha256'):
        api.read_trace_changes('codex', 'root', before['text_sha256'])
    assert api.read_trace_page(before['text_sha256'])['text'] == before['text']


def test_delta_pages_are_bounded_and_frozen_while_source_advances(tmp_path):
    api, source, *_ = setup(tmp_path)
    before = api.read_chat_context('codex', 'root')['snapshot_sha256']
    write_source(source, 'root', [command('a'), *[command(f'new-{n}') for n in range(9)]])
    page = api.read_trace_changes('codex', 'root', before, limit=2)
    after = page['snapshot_sha256']
    assert page['total_changes'] == 9 and page['next_offset'] == 2
    write_source(source, 'root', [command('a'), command('later')])
    records = list(page['items'])
    while page['next_offset'] is not None:
        page = api.read_trace_changes('codex', 'root', before, limit=2,
            offset=page['next_offset'], snapshot_sha256=after)
        assert len(page['items']) <= 2 and page['snapshot_sha256'] == after
        assert sum(len(group[key]) for group in page['changes'] for key in ('added', 'updated', 'removed')) <= 2
        records.extend(page['items'])
    assert {row['item']['item_id'] for row in records} == {f'new-{n}' for n in range(9)}
    with pytest.raises(ValueError, match='snapshot_sha256'):
        api.read_trace_changes('codex', 'root', before, offset=2)


def test_missing_child_is_partial_and_not_a_false_item_removal(tmp_path):
    api, source, child, _ = setup(tmp_path, children=True, reload=True)
    before = api.read_chat_context('codex', 'root', include_children=True)
    assert 'child-item' in before['text'] and before['partial'] is False
    child.unlink()
    context = api.read_chat_context('codex', 'root', include_children=True)
    assert context['partial'] and 'a' in context['text']
    assert context['availability'][-1] == {'session_id': 'child', 'status': 'unavailable', 'reason': 'source_missing'}
    changes = api.read_trace_changes('codex', 'root', before['snapshot_sha256'], include_children=True)
    assert changes['removed_sessions'] == []
    assert [row['change'] for row in changes['items']] == ['availability']
    assert api.read_trace_item('codex', 'child', 'child-item', before['snapshot_sha256'])['payload']['item']['exit_code'] == 0


def test_manifest_reload_only_discovers_explicit_registered_sources(tmp_path):
    api, source, child, manifest = setup(tmp_path, reload=True)
    before = api.read_chat_context('codex', 'root', include_children=True)
    write_source(child, 'child', [command('child-item')], 'root')
    write_source(tmp_path / 'unlisted.jsonl', 'unlisted', [command('not-registered')])
    assert len(api.search_trace_threads('')) == 1
    rows = json.loads(manifest.read_text())
    rows.append({'provider': 'codex', 'session_id': 'child', 'title': 'Child', 'path': child.name,
                 'parent_session_id': 'root'})
    manifest.write_text(json.dumps(rows))
    assert {row['session_id'] for row in api.search_trace_threads('')} == {'root', 'child'}
    context = api.read_chat_context('codex', 'root', include_children=True)
    assert 'child-item' in context['text'] and context['edges'][0]['recorded']
    assert context['snapshot_sha256'] != before['snapshot_sha256']


def test_bundle_identity_is_independent_of_checkout_location(tmp_path):
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.mkdir()
    api, *_ = setup(first, children=True)
    before = api.read_chat_context('codex', 'root', include_children=True)
    shutil.copytree(first, second)
    other = AgentTools(load_manifest(second / 'manifest.json'))
    relocated = other.read_chat_context('codex', 'root', include_children=True)
    assert relocated['snapshot_sha256'] == before['snapshot_sha256']
    assert relocated['text_sha256'] == before['text_sha256']


def test_sqlite_sources_are_an_explicit_library_only_boundary(tmp_path):
    source = tmp_path / 'history.sqlite'
    source.write_bytes(b'SQLite format 3\x00')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps([{'provider': 'codex', 'session_id': 'root', 'title': 'Root', 'path': source.name}]))
    with pytest.raises(ValueError, match='library-only'):
        load_manifest(manifest)


@pytest.mark.parametrize('failure,reason', [
    ('malformed', 'invalid_metadata'), ('permission', 'metadata_unreadable'),
    ('disappeared', 'metadata_unreadable')])
def test_child_header_failures_are_partial_through_live_manifest_loader(tmp_path, monkeypatch, failure, reason):
    api, _, child, _ = setup(tmp_path, children=True, reload=True)
    before = api.read_chat_context('codex', 'root', include_children=True)
    if failure == 'malformed':
        child.write_text('{not JSON}\n')
    else:
        original_open = Path.open
        def fail_header(path, *args, **kwargs):
            if path == child and kwargs.get('encoding') == 'utf-8':
                if failure == 'disappeared':
                    child.unlink(missing_ok=True)
                    raise FileNotFoundError('test race')
                raise PermissionError('test permission')
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', fail_header)
    after = api.read_chat_context('codex', 'root', include_children=True)
    assert after['partial'] and 'child-item' not in after['text']
    assert after['availability'][-1] == {'session_id': 'child', 'status': 'unavailable', 'reason': reason}
    assert api.read_trace_item('codex', 'child', 'child-item', before['snapshot_sha256'])['payload']['item']['exit_code'] == 0


def test_mixed_native_and_legacy_context_keeps_child_conversation(tmp_path):
    api, _, child, _ = setup(tmp_path, children=True, reload=True)
    write_source(child, 'child', [], 'root')
    with child.open('a') as stream:
        stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'legacy'}}) + '\n')
        stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'legacy child request'}}) + '\n')
        stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': 'legacy child answer'}}) + '\n')
    context = api.read_chat_context('codex', 'root', include_children=True)
    assert context['context_format'] == 'mixed'
    assert 'legacy child request' in context['text'] and 'legacy child answer' in context['text']
    assert context['native_item_coverage']['legacy_sessions'] == ['child']
    assert context['native_item_coverage']['native_sessions'] == ['root']


def test_recorded_identity_mismatch_is_rejected(tmp_path):
    api, source, *_ = setup(tmp_path)
    write_source(source, 'different-provider-id', [command('wrong')])
    with pytest.raises(ValueError, match='root source'):
        api.read_chat_context('codex', 'root')


@pytest.mark.parametrize('kwargs', [{'limit': 0}, {'limit': 101}, {'limit': True}, {'offset': -1}])
def test_delta_bounds_reject_invalid_values(tmp_path, kwargs):
    api, *_ = setup(tmp_path)
    baseline = api.read_chat_context('codex', 'root')['snapshot_sha256']
    with pytest.raises(ValueError):
        api.read_trace_changes('codex', 'root', baseline, **kwargs)
