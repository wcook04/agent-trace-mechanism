"""Native-item regressions; synthetic records below are test fixtures only."""
import hashlib
import json
import sqlite3

import pytest
from trace_mechanism import codex_native as native


def event(item, event_type='item_completed', session='session-a', **fields):
    return {'type': 'event_msg', 'payload': {'type': event_type, 'thread_id': session,
            'turn_id': 'turn-a', 'item': item, **fields}}


def write(path, records):
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))
    return path


def command(item_id='exec-native-uuid', **fields):
    return {'type': 'CommandExecution', 'id': item_id, 'command': ['sh', '-c', 'pytest'],
            'cwd': '/workspace', 'status': 'completed', 'exit_code': 1,
            'aggregated_output': 'real failure text', **fields}


def rendered_rows(text, snapshot=None):
    """Resolve renderer display references; source values come only from owner API."""
    blobs={}
    def resolve(value):
        if isinstance(value,list):return [resolve(v) for v in value]
        if not isinstance(value,dict):return value
        if 'evidence_ref' in value:
            ref=value['evidence_ref']
            assert ref['session_id']==snapshot['session_id']
            assert ref['snapshot_sha256']==snapshot['sha256']
            original=native.read_item(snapshot,ref['item_id'],field=ref['field'],limit=48000)
            if 'payload' in original:
                result=original['payload']
            else:
                parts=[original['payload_json']]
                while original['next_offset'] is not None:
                    original=native.read_item(snapshot,ref['item_id'],field=ref['field'],offset=original['next_offset'],limit=48000)
                    parts.append(original['payload_json'])
                result=json.loads(''.join(parts))
            assert hashlib.sha256(result.encode()).hexdigest()==ref['sha256']
            return result
        if 'blob_id' in value:
            blobs[value['blob_id']]=value['text'];return value['text']
        if 'blob_ref' in value:return blobs[value['blob_ref']]
        if 'text_parts' in value:return ''.join(resolve(v) for v in value['text_parts'])
        return {key:resolve(child) for key,child in value.items()}
    return [resolve(json.loads(line.removeprefix('Native item: '))) for line in text.splitlines() if line.startswith('Native item: ')]


def test_only_native_items_enter_timeline_and_no_raw_reasoning(tmp_path):
    path = write(tmp_path/'rollout.jsonl', [
        {'type': 'session_meta', 'payload': {'id': 'session-a', 'cwd': '/workspace'}},
        {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'functions.exec',
                                             'arguments': 'outer wrapper must not appear'}},
        event(command()),
        event({'type': 'Reasoning', 'id': 'hidden', 'summary_text': [], 'raw_content': ['hidden thoughts'],
               'encrypted_content': 'secret cipher'}),
        event({'type': 'Reasoning', 'id': 'visible', 'summary_text': ['Visible recorded summary'],
               'raw_content': ['not a visible summary']}),
    ])
    snap = native.load_rollout(path)
    assert [item['item_id'] for item in snap['items']] == ['exec-native-uuid', 'visible']
    assert snap['source']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert snap['items'][0]['source_refs'] == [{'record': 3, 'event_type': 'item_completed'}]
    assert snap['diagnostics']['ignored_native_items'] == 1
    assert 'hidden thoughts' not in json.dumps(snap) and 'secret cipher' not in json.dumps(snap)
    assert 'not a visible summary' not in json.dumps(snap)
    assert native.verify_snapshot(json.loads(json.dumps(snap)))
    snap['items'][0]['item']['exit_code'] = 0
    assert not native.verify_snapshot(snap)


def test_updates_replace_native_id_and_diff_does_not_count_as_added(tmp_path):
    path = write(tmp_path/'rollout', [event(command(status='in_progress', exit_code=None), 'item_started')])
    before = native.load_rollout(path)
    with path.open('a') as handle:
        handle.write(json.dumps(event(command(), started_at_ms=10, completed_at_ms=20))+'\n')
        handle.write(json.dumps(event({'type': 'AgentMessage', 'id': 'answer', 'content': [{'text': 'Done'}]}))+'\n')
    after = native.load_rollout(path)
    delta = native.diff_snapshots(before, after)
    assert [e['item_id'] for e in delta['added']] == ['answer']
    assert [e['item_id'] for e in delta['updated']] == ['exec-native-uuid']
    assert len(after['items'][0]['source_refs']) == 2
    assert after['items'][0]['first_record'] == 1
    assert before['items'][0]['item']['status'] == 'in_progress'
    assert native.render(after).count('\"kind\":\"CommandExecution\"') == 1
    # Repeated identical lifecycle payloads extend provenance but not semantic work.
    write(path, [event(command()), event(command())])
    a = native.load_rollout(path)
    write(path, [event(command())])
    b = native.load_rollout(path)
    assert native.diff_snapshots(a, b)['updated'] == []
    assert native.diff_snapshots(after, b)['removed'][0]['item_id'] == 'answer'


def test_native_id_is_scoped_to_exact_session_and_never_outer_call_id(tmp_path):
    a = native.load_rollout(write(tmp_path/'a', [event(command('exec-same'))]))
    b = native.load_rollout(write(tmp_path/'b', [event(command('exec-same'), session='session-b')]))
    assert a['items'][0]['session_id'] != b['items'][0]['session_id']
    with pytest.raises(ValueError, match='same exact session'):
        native.diff_snapshots(a, b)
    with pytest.raises(ValueError, match='session_meta'):
        native.load_rollout(write(tmp_path/'wrong', [{'type': 'session_meta', 'payload': {'id': 'wrong'}}]), 'expected')


def test_compact_omits_all_outputs_and_diffs_detail_deduplicates(tmp_path):
    repeated = 'repeated tool output ' * 100
    records = [event(command(aggregated_output=repeated)), event(command('exec-two', aggregated_output=repeated)),
               event({'type': 'FileChange', 'id': 'patch', 'changes': {'/workspace/a.py':
                     {'type': 'update', 'unified_diff': 'PRIVATE DIFF MARKER', 'move_path': None}},
                      'stdout': 'PATCH OUTPUT MARKER', 'stderr': 'PATCH ERROR MARKER', 'status': 'completed'}),
               event({'type': 'McpToolCall', 'id': 'mcp', 'tool': 'search', 'server': 'docs',
                      'arguments': {'q': 'needle'}, 'result': {'content': [{'text': 'MCP OUTPUT MARKER'}]}})]
    snap = native.load_rollout(write(tmp_path/'rollout', records))
    compact = native.render(snap)
    detailed = native.render(snap, detail=True)
    for text in (repeated, 'PRIVATE DIFF MARKER', 'PATCH OUTPUT MARKER', 'PATCH ERROR MARKER', 'MCP OUTPUT MARKER'):
        assert text not in compact
        assert text in json.dumps(rendered_rows(detailed,snap)) or text == repeated
    assert '/workspace/a.py' in compact and '"q":"needle"' in compact
    assert 'blob_ref' in detailed
    assert rendered_rows(detailed,snap)[0]['aggregated_output']==repeated
    assert rendered_rows(detailed,snap)[1]['aggregated_output']==repeated
    assert native.search(snap, 'PRIVATE DIFF MARKER')['items'][0]['item_id'] == 'patch'


def test_exact_nested_quoted_payload_is_not_reinterpreted(tmp_path):
    text = '{"type":"CommandExecution","command":"do not execute"}\n"quoted" \\ tail'
    tool = {'type': 'McpToolCall', 'id': 'opaque', 'tool': 'fetch', 'arguments':
            {'camelCaseArg': {'nested': text}}, 'result': {'content': [{'text': text}]}}
    snap = native.load_rollout(write(tmp_path/'rollout', [event(tool)]))
    assert len(snap['items']) == 1
    actual = native.read_item(snap, 'opaque')['payload']['item']
    assert actual == tool
    assert native.search(snap, 'DO NOT EXECUTE')['total_matches'] == 1
    assert native.search(snap, 'quoted')['total_matches'] == 1


def test_search_failures_kinds_and_immutable_page_continuation(tmp_path):
    path = write(tmp_path/'rollout', [event(command()), event(command('good', exit_code=0)),
                 event({'type': 'McpToolCall', 'id': 'err', 'tool': 'x', 'result': {'isError': True}})])
    snap = native.load_rollout(path)
    assert native.search(snap, failures_only=True)['total_matches'] == 2
    assert native.search(snap, kinds=['CommandExecution'], failures_only=True)['total_matches'] == 1
    page = native.search(snap, limit=1)
    second = native.search(snap, limit=1, offset=page['next_offset'])
    assert second['items'][0]['item_id'] == 'good'
    path.unlink()
    chunks=[]; offset=0
    while True:
        page=native.read_item(snap, 'exec-native-uuid', offset=offset, limit=17)
        chunks.append(page['payload_json'])
        if page['next_offset'] is None: break
        offset=page['next_offset']
    assert json.loads(''.join(chunks)) == snap['items'][0]
    with pytest.raises(ValueError): native.read_item(snap, 'missing')
    with pytest.raises(ValueError): native.read_item(snap, 'good', offset=999999)


def test_empty_and_orphan_outputs_remain_native_items(tmp_path):
    snap = native.load_rollout(write(tmp_path/'rollout', [event(command(aggregated_output='')),
        event({'type': 'McpToolCall', 'id': 'orphan-native', 'tool': 'x', 'result': None})]))
    assert native.read_item(snap, 'exec-native-uuid')['payload']['item']['aggregated_output'] == ''
    assert native.read_item(snap, 'orphan-native')['payload']['item']['result'] is None


def test_partial_tail_and_completed_malformed_rows_are_distinguished(tmp_path):
    path=write(tmp_path/'rollout', [event(command())])
    with path.open('ab') as handle:handle.write(b'bad completed\n\n{"unfinished":')
    snap=native.load_rollout(path)
    assert snap['diagnostics']['malformed_records'] == 1
    assert snap['diagnostics']['malformed_lines'] == [2]
    assert snap['diagnostics']['pending_records'] == 1
    assert snap['items'][0]['source_refs'][0]['record'] == 1


def test_settings_once_per_change_and_native_message_types(tmp_path):
    records=[{'type':'turn_context','payload':{'model':'model-a','effort':'high','cwd':'/w'}},
             event({'type':'UserMessage','id':'user','content':[{'type':'text','text':'Question'}]}),
             {'type':'turn_context','payload':{'model':'model-a','effort':'high','cwd':'/w'}},
             event({'type':'AgentMessage','id':'answer','phase':'final','content':[{'text':'Answer'}]}),
             {'type':'turn_context','payload':{'model':'model-a','effort':'low','cwd':'/w'}},
             event({'type':'SubAgentActivity','id':'spawn','kind':'spawned','agent_thread_id':'exact-child'}),
             event({'type':'Extension','kind':'webSearch','id':'web','query':'find this','results':[]})]
    snap=native.load_rollout(write(tmp_path/'rollout',records))
    assert len(snap['settings']) == 2 and snap['settings'][1]['values'] == {'effort':'low'}
    text=native.render(snap)
    assert text.count('model-a') == 1 and 'exact-child' in text
    assert 'Question' in text and 'Answer' in text


def test_old_rollout_does_not_invent_native_items(tmp_path):
    snap=native.load_rollout(write(tmp_path/'rollout',[{'type':'response_item','payload':{'type':'message'}}]),'explicit')
    assert snap['items']==[] and snap['has_native_items'] is False


@pytest.mark.parametrize('kwargs',[{'limit':0},{'limit':101},{'offset':-1},{'query':'x'*2049},
                                  {'kinds':['invented']},{'failures_only':'yes'}])
def test_search_bounds(tmp_path,kwargs):
    snap=native.load_rollout(write(tmp_path/'rollout',[event(command())]))
    with pytest.raises(ValueError): native.search(snap,**kwargs)


def test_sqlite_is_readonly_and_normalizes_camel_case_without_mutating_args(tmp_path):
    path=tmp_path/'history.sqlite'
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE thread_items(thread_id,turn_id,item_id,rollout_ordinal,item_json)')
        connection.execute('INSERT INTO thread_items VALUES(?,?,?,?,?)',('session-a','turn','native',42,json.dumps({
            'type':'commandExecution','id':'native','command':['test'],'exitCode':1,'aggregatedOutput':'failed'})))
        connection.execute('INSERT INTO thread_items VALUES(?,?,?,?,?)',('other','turn','excluded',43,json.dumps({
            'type':'agentMessage','id':'excluded','content':[{'text':'other session'}]})))
    before=path.read_bytes()
    snap=native.load_history(path,'session-a')
    assert path.read_bytes()==before
    assert len(snap['items'])==1 and snap['items'][0]['kind']=='CommandExecution'
    assert snap['items'][0]['item']['exit_code']==1
    assert snap['items'][0]['source_refs']==[{'rollout_ordinal':42,'event_type':'history_projection'}]
    assert native.verify_snapshot(snap)


def test_compact_bounds_large_commands_and_args_with_exact_drilldown(tmp_path):
    script = 'run-important-command\n' + 'x' * 30000
    tool = {'type':'McpToolCall','id':'longargs','tool':'code','arguments':{'code':script}}
    snap = native.load_rollout(write(tmp_path/'rollout', [event(command(command=['sh','-c',script])), event(tool)]))
    compact=native.render(snap)
    assert len(compact)<2500
    assert script not in compact and 'command_truncated' in compact
    assert native.read_item(snap,'exec-native-uuid',limit=48000)['payload']['item']['command'][2]==script
    assert 'evidence_ref' in native.render(snap,True)
    assert rendered_rows(native.render(snap,True),snap)[0]['command'][2]==script


def test_forest_dedup_shares_blobs_and_retains_exact_session_headers(tmp_path):
    output='shared opaque output '*200
    a=native.load_rollout(write(tmp_path/'a',[event(command(aggregated_output=output))]))
    b=native.load_rollout(write(tmp_path/'b',[event(command(aggregated_output=output),session='session-b')]))
    text=native.render_many([a,b],True)
    assert 'blob_ref' in text and 'evidence_ref' in text
    assert text.count('Native snapshot: ')==2
    assert 'session-a' in text and 'session-b' in text


def test_web_variants_visible_reasoning_and_typed_lean_framing(tmp_path):
    snap=native.load_rollout(write(tmp_path/'rollout',[
        event({'type':'Extension','kind':'web.search','id':'search','query':'question','results':[]}),
        event({'type':'SubAgentActivity','kind':'spawned','id':'spawn','agent_thread_id':'child'})]))
    rows=[json.loads(line.removeprefix('Native item: ')) for line in native.render(snap).splitlines()
          if line.startswith('Native item: ')]
    assert rows[0]['kind']=='Extension' and rows[0]['native_kind']=='web.search'
    assert rows[1]['kind']=='SubAgentActivity' and rows[1]['native_kind']=='spawned'
    assert 'session_id' not in rows[0] and 'source_sha256' not in rows[0]
    assert native.summary(snap)['kinds']=={'Extension':1,'SubAgentActivity':1}


def test_semantic_diff_ignores_timestamp_and_duplicate_provenance(tmp_path):
    a=native.load_rollout(write(tmp_path/'a',[event(command(),started_at_ms=1,completed_at_ms=2)]))
    b=native.load_rollout(write(tmp_path/'b',[event(command(),started_at_ms=3,completed_at_ms=4)]))
    assert native.diff_snapshots(a,b)['updated']==[]


def test_exact_multiline_and_quoted_output_search_and_single_body_read(tmp_path):
    output='first line\n"quoted" second line'
    snap=native.load_rollout(write(tmp_path/'rollout',[event(command(aggregated_output=output))]))
    assert native.search(snap,output)['total_matches']==1
    complete=native.read_item(snap,'exec-native-uuid')
    assert 'payload' in complete and 'payload_json' not in complete
    partial=native.read_item(snap,'exec-native-uuid',limit=8)
    assert 'payload_json' in partial and 'payload' not in partial


def test_duplicate_mcp_structured_body_referenced_without_changing_native(tmp_path):
    body={'answer':['exact structured body',{'nested':True}]}
    original={'type':'McpToolCall','id':'dupe','tool':'lookup','result':{
        'content':[{'type':'text','text':json.dumps(body)}],'structuredContent':body}}
    snap=native.load_rollout(write(tmp_path/'rollout',[event(original)]))
    text=native.render(snap,True)
    assert text.count('exact structured body')==1 and '"json_ref":"structuredContent"' in text
    assert native.read_item(snap,'dupe')['payload']['item']==original


def test_empty_latest_reasoning_replaces_prior_visible_update(tmp_path):
    snap=native.load_rollout(write(tmp_path/'rollout',[
        event({'type':'Reasoning','id':'r','summary_text':['visible']},'item_started'),
        event({'type':'Reasoning','id':'r','summary_text':[]})]))
    assert snap['items']==[]


def test_source_location_is_provenance_not_snapshot_or_render_identity(tmp_path):
    left=tmp_path/'one'/'original.jsonl';left.parent.mkdir()
    right=tmp_path/'two'/'renamed.jsonl';right.parent.mkdir()
    records=[event(command())]
    a=native.load_rollout(write(left,records))
    b=native.load_rollout(write(right,records))
    assert a['source']['path']==str(left.resolve())
    assert b['source']['path']==str(right.resolve())
    assert a['source']['sha256']==b['source']['sha256']
    assert a['sha256']==b['sha256']
    assert native.render(a)==native.render(b)
    assert native.render(a,True)==native.render(b,True)
    assert native.verify_snapshot(a) and native.verify_snapshot(b)
    assert str(tmp_path) not in native.render(a)
    b['source']['sha256']='changed source digest'
    assert not native.verify_snapshot(b)


def test_detailed_large_fields_are_expandable_exact_and_keep_failure_tail(tmp_path):
    output='source output line\n'*2000+'ERROR: final real failure'
    patch='diff body\n'*1000
    snap=native.load_rollout(write(tmp_path/'rollout',[
        event(command(aggregated_output=output)),
        event({'type':'FileChange','id':'patch','changes':{'/a~b/c':{'type':'update','unified_diff':patch}},'status':'completed'})]))
    text=native.render(snap,True)
    assert len(text)<6000
    assert 'ERROR: final real failure' in text and output not in text
    assert 'evidence_ref' in text and '/changes/~1a~0b~1c/unified_diff' in text
    rows=rendered_rows(text,snap)
    assert rows[0]['aggregated_output']==output and rows[0]['exit_code']==1
    assert rows[1]['changes']['/a~b/c']['unified_diff']==patch
    assert native.search(snap,'source output line\nsource output line')['total_matches']==1
    exact=native.read_item(snap,'exec-native-uuid',field='/aggregated_output',limit=48000)
    assert exact['payload']==output


def test_shared_exact_blocks_inside_different_outputs_appear_once(tmp_path):
    common='shared evidence block '*28
    a=common+'unique first ending'
    b=common+'unique second ending'
    snap=native.load_rollout(write(tmp_path/'rollout',[event(command('a',aggregated_output=a)),event(command('b',aggregated_output=b))]))
    text=native.render(snap,True)
    assert 'blob_id' in text and 'blob_ref' in text
    rows=rendered_rows(text,snap)
    assert rows[0]['aggregated_output']==a and rows[1]['aggregated_output']==b


@pytest.mark.parametrize('field',['relative','/~2bad','/command/-1','/command/01','/missing','/command/999','/'+'x'*2048])
def test_json_pointer_rejects_invalid_or_missing_fields(tmp_path,field):
    snap=native.load_rollout(write(tmp_path/'rollout',[event(command())]))
    with pytest.raises(ValueError):native.read_item(snap,'exec-native-uuid',field=field)


def test_field_reads_page_only_requested_original_value(tmp_path):
    output='"quoted"\n' * 2000
    snap=native.load_rollout(write(tmp_path/'rollout',[event(command(aggregated_output=output))]))
    chunks=[];offset=0
    while True:
        page=native.read_item(snap,'exec-native-uuid',field='/aggregated_output',offset=offset,limit=31)
        assert page['field']=='/aggregated_output'
        chunks.append(page['payload_json'])
        if page['next_offset'] is None:break
        offset=page['next_offset']
    assert json.loads(''.join(chunks))==output
    assert native.read_item(snap,'exec-native-uuid',field='/command/0')['payload']=='sh'
