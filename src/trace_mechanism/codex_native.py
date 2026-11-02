"""Canonical Codex native items, independent of private application infrastructure.

Only recorded native items enter the timeline. Outer response_item tool calls,
configuration injections and encrypted reasoning never enter it. Callers choose
sources and persist JSONable snapshots; this module never discovers home files.

Retrieval preserves captured normalized JSON values, not original JSONL bytes:
known item/field names normalize; unsupported types, encrypted fields and raw
reasoning are excluded. Source SHA-256 and record references identify the read
source, whose upstream payloads may themselves be truncated. Rendered detail is
an evidence projection; immutable field reads return retained normalized values.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import sqlite3

MAX_SOURCE_BYTES = 256 * 1024 * 1024
MAX_RECORD_BYTES = 24 * 1024 * 1024
MAX_ITEMS = 100000
MAX_QUERY_CHARS = 2048
MAX_PAGE_CHARS = 48000
MAX_INLINE_TEXT_CHARS = 2400
INLINE_HEAD_CHARS = 512
INLINE_TAIL_CHARS = 256
_SCHEMA = 'codex_native_v1'
_ITEM_EVENTS = {'item_started', 'item_updated', 'item_completed'}
_KINDS = {k.casefold(): k for k in ('CommandExecution', 'FileChange', 'McpToolCall',
          'AgentMessage', 'UserMessage', 'Reasoning', 'SubAgentActivity', 'Extension', 'ContextCompaction')}
_TOP_KEYS = {'aggregatedOutput': 'aggregated_output', 'exitCode': 'exit_code',
             'processId': 'process_id', 'parsedCmd': 'parsed_cmd',
             'summaryText': 'summary_text', 'agentThreadId': 'agent_thread_id',
             'agentPath': 'agent_path', 'reasoningEffort': 'reasoning_effort',
             'rawContent': 'raw_content', 'summary': 'summary_text', 'durationMs': 'duration_ms'}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _bounded_int(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'{name} must be an integer between {lower} and {upper}.')


def _sanitize(value):
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()
                if not k.casefold().startswith('encrypted')}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(filter(None, (_text(v) for v in value)))
    if isinstance(value, dict):
        return value.get('text', '') if isinstance(value.get('text'), str) else ''
    return ''


def _type_token(value) -> str:
    return str(value).replace('_', '').casefold()


def _message_text(item: dict) -> str:
    # App Server's published agentMessage uses text; rollout items can use
    # content blocks. An explicitly recorded empty text remains authoritative.
    return item['text'] if isinstance(item.get('text'), str) else _text(item.get('content'))


def _normalize(item: dict) -> dict | None:
    item = _sanitize(item)
    for alias, canonical in _TOP_KEYS.items():
        if alias in item and canonical not in item:
            item[canonical] = item.pop(alias)
    # When both spellings are recorded, retain both values without overwriting;
    # the canonical spelling drives projections and both stay field-readable.
    wire_type = _type_token(item.get('type', ''))
    if wire_type == 'websearch':
        item['kind'] = 'web.search'
        wire_type = 'extension'
    kind = _KINDS.get(wire_type)
    if not kind or not isinstance(item.get('id'), str) or not item['id'] or len(item['id']) > 512:
        return None
    item['type'] = kind
    if kind == 'Reasoning':
        summary = _text(item.get('summary_text'))
        if not summary.strip():
            return None
        # Only the explicitly recorded visible summary is eligible.
        item = {'id': item['id'], 'type': kind, 'summary_text': item['summary_text']}
    if kind == 'Extension' and _type_token(item.get('kind')) not in ('websearch', 'web.search'):
        return None
    return item


def _settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    result = {}
    for key, aliases in {'model': ('model',), 'effort': ('effort', 'reasoning_effort', 'reasoningEffort'),
                         'cwd': ('cwd',)}.items():
        for alias in aliases:
            if isinstance(payload.get(alias), str):
                result[key] = payload[alias]
                break
    return result


def _new_snapshot(session_id: str | None, source: dict) -> dict:
    return {'schema': _SCHEMA, 'session_id': session_id, 'source': source, 'settings': [],
            'has_native_items': False, 'items': [],
            'diagnostics': {'native_item_count': 0, 'native_events': 0, 'ignored_native_items': 0,
                            'malformed_records': 0, 'malformed_lines': [], 'pending_records': 0,
                            'oversized_records': 0, 'identity_mismatches': 0}}


def _add_item(snapshot: dict, by_id: dict, item: dict, *, turn_id, record: int, event_type: str,
              started_at_ms=None, completed_at_ms=None):
    snapshot['diagnostics']['native_events'] += 1
    normalized = _normalize(item)
    if normalized is None:
        snapshot['diagnostics']['ignored_native_items'] += 1
        if _type_token(item.get('type', '')) == 'reasoning' and isinstance(item.get('id'), str):
            by_id.pop(item.get('id'), None)
        return
    item_id = normalized['id']
    previous = by_id.get(item_id)
    if previous is None and len(by_id) >= MAX_ITEMS:
        raise ValueError('Native snapshot exceeds the item limit.')
    refs = list(previous['source_refs']) if previous else []
    refs.append({'record': record, 'event_type': event_type})
    content = {'session_id': snapshot['session_id'], 'item_id': item_id, 'kind': normalized['type'],
               'turn_id': turn_id if turn_id is not None else (previous or {}).get('turn_id'),
               'status': normalized.get('status'), 'item': normalized,
               'started_at_ms': started_at_ms, 'completed_at_ms': completed_at_ms}
    entry = {**content, 'sha256': _sha({'session_id': snapshot['session_id'], 'item': normalized}), 'source_refs': refs,
             'first_record': previous['first_record'] if previous else record}
    by_id[item_id] = entry


def _snapshot_sha(snapshot: dict) -> str:
    # Capture location is local provenance, never content identity. Retaining it
    # lets private adapters validate their source cache without making portable
    # regenerated snapshots or rendered headers depend on a checkout directory.
    content = {key: value for key, value in snapshot.items() if key != 'sha256'}
    content['source'] = {key: value for key, value in snapshot['source'].items() if key != 'path'}
    return _sha(content)


def _finish(snapshot: dict, by_id: dict) -> dict:
    snapshot['items'] = list(by_id.values())
    snapshot['diagnostics']['native_item_count'] = len(by_id)
    snapshot['has_native_items'] = bool(by_id)
    snapshot['sha256'] = _snapshot_sha(snapshot)
    return snapshot


def verify_snapshot(snapshot: dict) -> bool:
    """Check a persisted JSON snapshot without consulting its advancing source."""
    return (isinstance(snapshot, dict) and snapshot.get('schema') == _SCHEMA
            and isinstance(snapshot.get('sha256'), str)
            and _snapshot_sha(snapshot) == snapshot['sha256'])


def load_rollout(path: str | Path, session_id: str | None = None) -> dict:
    """Read native lifecycle items once, preserving original physical line handles.

    Later updates replace the same (session_id,item_id), retaining all source
    references. A malformed unterminated tail is pending rather than corruption.
    No call attribution is inferred from text, timestamps or outer tool IDs.
    """
    path = Path(path)
    with path.open('rb') as handle:
        raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError('Rollout exceeds the bounded source size.')
    snapshot = _new_snapshot(session_id, {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
                                         'bytes': len(raw), 'kind': 'rollout_jsonl'})
    by_id = {}
    settings = {}
    for number, line in enumerate(io.BytesIO(raw), 1):
        if not line.strip():
            continue
        if len(line) > MAX_RECORD_BYTES:
            snapshot['diagnostics']['oversized_records'] += 1
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError('JSON record must be an object.')
        except (ValueError, UnicodeDecodeError, RecursionError):
            if not line.endswith(b'\n'):
                snapshot['diagnostics']['pending_records'] += 1
            else:
                snapshot['diagnostics']['malformed_records'] += 1
                if len(snapshot['diagnostics']['malformed_lines']) < 20:
                    snapshot['diagnostics']['malformed_lines'].append(number)
            continue
        payload = record.get('payload')
        if not isinstance(payload, dict):
            continue
        if record.get('type') == 'session_meta':
            observed_id = payload.get('id')
            if snapshot['session_id'] and observed_id and observed_id != snapshot['session_id']:
                raise ValueError('Requested session ID does not match recorded session_meta.id.')
            if observed_id:
                snapshot['session_id'] = observed_id
            next_settings = _settings(payload)
        elif record.get('type') == 'turn_context':
            next_settings = _settings(payload)
        elif record.get('type') == 'event_msg' and payload.get('type') == 'thread_settings_applied':
            next_settings = _settings(payload.get('thread_settings') or {})
        else:
            next_settings = {}
        changed = {k: v for k, v in next_settings.items() if settings.get(k) != v}
        if changed:
            settings.update(changed)
            snapshot['settings'].append({'record': number, 'values': changed})
        if record.get('type') != 'event_msg' or payload.get('type') not in _ITEM_EVENTS:
            continue
        if not snapshot['session_id']:
            snapshot['session_id'] = payload.get('thread_id')
        if payload.get('thread_id') and payload['thread_id'] != snapshot['session_id']:
            snapshot['diagnostics']['identity_mismatches'] += 1
            continue
        if isinstance(payload.get('item'), dict):
            try:
                _add_item(snapshot, by_id, payload['item'], turn_id=payload.get('turn_id'), record=number,
                          event_type=payload['type'], started_at_ms=payload.get('started_at_ms'),
                          completed_at_ms=payload.get('completed_at_ms'))
            except (RecursionError, OverflowError, ValueError):
                if len(by_id) >= MAX_ITEMS:
                    raise
                snapshot['diagnostics']['malformed_records'] += 1
    if not isinstance(snapshot['session_id'], str) or not snapshot['session_id']:
        raise ValueError('No exact session identity recorded; supply session_id.')
    return _finish(snapshot, by_id)


def load_history(sqlite_path: str | Path, session_id: str) -> dict:
    """Read the existing thread_items projection in a read-only SQLite transaction.

    CamelCase wire fields normalize to the same native item model. The source
    digest covers selected rows, since an SQLite WAL may hold committed history.
    rollout_ordinal is retained as a projection ordinal, not a physical line.
    """
    path = Path(sqlite_path).resolve()
    if not isinstance(session_id, str) or not session_id or len(session_id) > 512:
        raise ValueError('Supply an exact session ID.')
    by_id = {}
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        columns = {row[1] for row in connection.execute('PRAGMA table_info(thread_items)')}
        required = {'thread_id', 'turn_id', 'item_id', 'rollout_ordinal', 'item_json'}
        if not required <= columns:
            raise ValueError('Native thread_items schema is unavailable.')
        rows = connection.execute('SELECT turn_id,item_id,rollout_ordinal,item_json FROM thread_items '
                                  'WHERE thread_id=? ORDER BY rollout_ordinal,item_id LIMIT ?',
                                  (session_id, MAX_ITEMS + 1)).fetchall()
    if len(rows) > MAX_ITEMS or sum(len(row[3]) for row in rows) > MAX_SOURCE_BYTES:
        raise ValueError('Native history exceeds the bounded source size.')
    snapshot = _new_snapshot(session_id, {'path': str(path), 'kind': 'thread_items_sqlite',
                                         'sha256': _sha(rows), 'hash_scope': 'selected_rows'})
    for turn_id, item_id, ordinal, encoded in rows:
        try:
            item = json.loads(encoded)
            if not isinstance(item, dict) or item.get('id') != item_id:
                raise ValueError('Projection item identity mismatch.')
            _add_item(snapshot, by_id, item, turn_id=turn_id, record=ordinal,
                      event_type='history_projection')
        except (ValueError, RecursionError):
            snapshot['diagnostics']['malformed_records'] += 1
    for entry in by_id.values():
        for ref in entry['source_refs']:
            ref['rollout_ordinal'] = ref.pop('record')
    return _finish(snapshot, by_id)


def _failed(entry: dict) -> bool:
    item = entry['item']
    if type(item.get('exit_code')) is int and item['exit_code'] != 0:
        return True
    if str(item.get('status', '')).casefold() in ('failed', 'error', 'declined', 'cancelled', 'canceled'):
        return True
    result = item.get('result')
    return bool(item.get('error') or (isinstance(result, dict) and (result.get('isError') or result.get('is_error'))))


def _descriptor(entry: dict) -> dict:
    item = entry['item']
    preview = item.get('command') if entry['kind'] == 'CommandExecution' else (
        item.get('tool') if entry['kind'] == 'McpToolCall' else
        item.get('summary_text') if entry['kind'] == 'Reasoning' else
        _message_text(item) if entry['kind'] in ('AgentMessage', 'UserMessage') else item.get('content', item.get('kind', '')))
    if not isinstance(preview, str):
        preview = _text(preview) or _json(preview)
    return {k: entry.get(k) for k in ('session_id', 'item_id', 'kind', 'turn_id', 'status', 'sha256', 'first_record')} | {
        'failed': _failed(entry), 'excerpt': preview[:400], 'source_refs': entry['source_refs'][-10:],
        'source_ref_count': len(entry['source_refs'])}


def _match_excerpt(text: str, needle: str, field: str, encoding: str) -> dict | None:
    folded = text.casefold()
    start = folded.find(needle)
    if start < 0:
        return None
    end = start + len(needle)
    if len(folded) != len(text):
        # Case folding can expand a character (e.g. Straße -> strasse). Keep
        # offsets in original Unicode characters, rather than folded positions.
        original_start = original_end = None
        cursor = 0
        for index, char in enumerate(text):
            cursor_end = cursor + len(char.casefold())
            if original_start is None and cursor_end > start:
                original_start = index
            if cursor_end >= end:
                original_end = index + 1
                break
            cursor = cursor_end
        start = original_start if original_start is not None else start
        end = original_end if original_end is not None else end
    excerpt_start = max(0, start - 120)
    excerpt_end = min(len(text), max(end, start + 280), excerpt_start + 400)
    return {'field': field, 'encoding': encoding, 'value_offset': start, 'value_end': end,
            'excerpt_offset': excerpt_start, 'offset_unit': 'unicode_characters',
            'excerpt': text[excerpt_start:excerpt_end]}


def _find_match(value, needle: str, pointer: str = '') -> dict | None:
    if isinstance(value, str):
        return _match_excerpt(value, needle, pointer, 'decoded_text')
    if isinstance(value, dict):
        for key, child in value.items():
            field = pointer + '/' + _pointer_part(key)
            match = _find_match(child, needle, field)
            if match:
                return match
            match = _match_excerpt(key, needle, field, 'field_name')
            if match:
                return match
    elif isinstance(value, list):
        for index, child in enumerate(value):
            match = _find_match(child, needle, pointer + '/' + str(index))
            if match:
                return match
    else:
        return _match_excerpt(_json(value), needle, pointer, 'canonical_json')
    return None


def search(snapshot: dict, query: str = '', kinds: list[str] | None = None,
           failures_only: bool = False, limit: int = 20, offset: int = 0) -> dict:
    """Case-insensitive literal substring search, including complete outputs/diffs.

    Results are bounded handles, never tool outputs. kinds accepts exact native
    names. offset pages this immutable snapshot; it is not a live-file cursor.
    """
    if not isinstance(query, str) or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f'query must contain at most {MAX_QUERY_CHARS} characters.')
    _bounded_int(limit, 'limit', 1, 100)
    _bounded_int(offset, 'offset', 0, MAX_ITEMS)
    if kinds is not None and (not isinstance(kinds, list) or len(kinds) > len(_KINDS)
                              or any(k not in _KINDS.values() for k in kinds)):
        raise ValueError('kinds must list supported native item types.')
    if type(failures_only) is not bool:
        raise ValueError('failures_only must be a boolean.')
    needle = query.casefold()
    matches = []
    for entry in snapshot['items']:
        if (kinds is not None and entry['kind'] not in kinds) or (failures_only and not _failed(entry)):
            continue
        match = None
        if needle:
            match = _find_match(entry['item'], needle)
            if match is None:
                # Preserve literal structured-JSON queries as an explicit
                # representation match; ordinary output hits point at the leaf.
                match = _match_excerpt(_json(entry['item']), needle, '', 'canonical_json')
            if match is None:
                continue
        matches.append((entry, match))
    end = min(len(matches), offset + limit)
    descriptors = []
    for entry, match in matches[offset:end]:
        descriptor = _descriptor(entry)
        if match:
            descriptor['excerpt'] = match.pop('excerpt')
            descriptor['match'] = match
        descriptors.append(descriptor)
    return {'sha256': snapshot['sha256'], 'items': descriptors,
            'total_matches': len(matches), 'offset': offset, 'next_offset': end if end < len(matches) else None,
            'offset_unit': 'matching_items'}


def read_item(snapshot: dict, item_id: str, offset: int = 0, limit: int = 24000, field: str = '') -> dict:
    """Page captured normalized JSON, or one field relative to its native item.

    Empty field returns the captured whole entry. A field returns only that
    value. Partial pages concatenate to canonical JSON, including JSON string
    quotes/escapes. String evidence SHA values hash the original UTF-8 text.
    """
    _bounded_int(offset, 'offset', 0, MAX_SOURCE_BYTES)
    _bounded_int(limit, 'limit', 1, MAX_PAGE_CHARS)
    entry = next((entry for entry in snapshot['items'] if entry['item_id'] == item_id), None)
    if entry is None:
        raise ValueError('Native item does not exist in this snapshot.')
    value = entry
    if not isinstance(field, str) or len(field) > 2048 or (field and not field.startswith('/')):
        raise ValueError('field must be a bounded JSON Pointer relative to the native item.')
    if field:
        segments = field[1:].split('/')
        if len(segments) > 64:
            raise ValueError('field JSON Pointer is too deep.')
        value = entry['item']
        for segment in segments:
            for index, char in enumerate(segment):
                if char == '~' and (index + 1 >= len(segment) or segment[index + 1] not in '01'):
                    raise ValueError('Invalid JSON Pointer escape.')
            key = segment.replace('~1', '/').replace('~0', '~')
            if isinstance(value, dict) and key in value:
                value = value[key]
            elif isinstance(value, list) and key.isascii() and key.isdigit() and str(int(key)) == key and int(key) < len(value):
                value = value[int(key)]
            else:
                raise ValueError('field does not exist in the native item.')
    body = _json(value)
    if offset > len(body):
        raise ValueError('offset is beyond the native item.')
    end = min(len(body), offset + limit)
    result = {'sha256': snapshot['sha256'], 'item_id': item_id,
              'offset': offset, 'next_offset': end if end < len(body) else None, 'total_chars': len(body), 'field': field,
              'representation': 'captured_normalized_value', 'page_encoding': 'canonical_json',
              'offset_unit': 'unicode_characters'}
    if offset == 0 and end == len(body):
        result['payload'] = value
    else:
        result['payload_json'] = body[offset:end]
    return result


def diff_snapshots(before: dict, after: dict) -> dict:
    """Distinguish updated native IDs from new work, within one exact session."""
    if before['session_id'] != after['session_id']:
        raise ValueError('Compare snapshots of the same exact session.')
    old = {entry['item_id']: entry for entry in before['items']}
    new = {entry['item_id']: entry for entry in after['items']}
    return {'before_sha256': before['sha256'], 'after_sha256': after['sha256'],
            'added': [_descriptor(entry) for key, entry in new.items() if key not in old],
            'updated': [_descriptor(entry) for key, entry in new.items() if key in old and entry['sha256'] != old[key]['sha256']],
            'removed': [_descriptor(entry) for key, entry in old.items() if key not in new]}


def _compact_item(entry: dict) -> dict:
    item = entry['item']
    kind = entry['kind']
    if kind == 'CommandExecution':
        result = {k: item[k] for k in ('cwd', 'status', 'exit_code', 'duration_ms') if k in item}
        command = item.get('command', [])
        encoded = _json(command)
        if len(encoded) <= 240:
            result['command'] = command
        elif isinstance(command, list):
            remaining = 240
            preview = []
            for arg in command:
                if remaining <= 0:
                    break
                text = arg if isinstance(arg, str) else _json(arg)
                preview.append(text[:remaining])
                remaining -= len(text)
            result.update(command=preview, command_chars=len(encoded), command_truncated=True)
        else:
            result.update(command=str(command)[:240], command_chars=len(encoded), command_truncated=True)
        return result
    if kind == 'FileChange':
        changes = item.get('changes', {})
        if isinstance(changes, dict):
            paths = [{'path': path, 'change': change.get('type'),
                      **({'move_path': change.get('move_path', change.get('movePath'))}
                         if change.get('move_path', change.get('movePath')) else {})}
                     for path, change in changes.items() if isinstance(change, dict)]
        else:
            paths = [{'path': c.get('path'), 'change': c.get('kind', c.get('type'))}
                     for c in changes if isinstance(c, dict)]
        return {'changes': paths, 'status': item.get('status')}
    if kind == 'McpToolCall':
        args = _json(item.get('arguments', {}))
        return {'server': item.get('server'), 'tool': item.get('tool'), 'status': item.get('status'),
                'arguments': item.get('arguments', {}) if len(args) <= 800 else {'preview': args[:700], 'chars': len(args)},
                **({'duration_ms': item['duration_ms']} if 'duration_ms' in item else {})}
    if kind in ('UserMessage', 'AgentMessage'):
        return {'text': _message_text(item), **({'phase': item['phase']} if 'phase' in item else {})}
    if kind == 'Reasoning':
        return {'visible_summary': _text(item.get('summary_text'))}
    if kind == 'Extension':
        return {k: item[k] for k in ('kind', 'query', 'action', 'status') if k in item}
    return {k: v for k, v in item.items() if k not in ('id', 'type', 'result', 'output', 'results')}


def summary(snapshot: dict) -> dict:
    """Return bounded inventory without including private item contents."""
    return {'schema': snapshot['schema'], 'sha256': snapshot['sha256'],
            'session_id': snapshot['session_id'], 'item_count': len(snapshot['items']),
            'kinds': dict(Counter(entry['kind'] for entry in snapshot['items'])),
            'failures': sum(_failed(entry) for entry in snapshot['items']),
            'diagnostics': snapshot['diagnostics']}


def _dedup_result_envelopes(value):
    """Reference an exact duplicate JSON text/structuredContent body once.

    This is equality checking for a display projection, never interpretation of
    an embedded tool event. The original native payload remains in the snapshot.
    """
    if isinstance(value, list):
        return [_dedup_result_envelopes(child) for child in value]
    if not isinstance(value, dict):
        return value
    result = {key: _dedup_result_envelopes(child) for key, child in value.items()}
    structured_key = next((key for key in ('structuredContent', 'structured_content') if key in value), None)
    if structured_key and isinstance(value.get('content'), list):
        projected = []
        for block in value['content']:
            equal = False
            if isinstance(block, dict) and isinstance(block.get('text'), str):
                try:
                    equal = json.loads(block['text']) == value[structured_key]
                except (ValueError, RecursionError):
                    pass
            if equal:
                projected.append({**{key: child for key, child in block.items() if key != 'text'},
                                  'json_ref': structured_key})
            else:
                projected.append(_dedup_result_envelopes(block))
        result['content'] = projected
    return result


def _detailed_item(entry: dict) -> dict:
    result = _compact_item(entry)
    item = entry['item']
    if entry['kind'] == 'CommandExecution':
        result['command'] = item.get('command', [])
        result.pop('command_chars', None)
        result.pop('command_truncated', None)
        if 'duration' in item:
            result['duration'] = item['duration']
    if entry['kind'] == 'FileChange':
        result['changes'] = item.get('changes', {})
    # The same primary representation gains outputs. Derived parsed_cmd and
    # repeated lifecycle/configuration wrappers remain owned by read_item.
    for key in ('aggregated_output', 'output', 'stdout', 'stderr', 'result', 'results', 'error'):
        if key in item:
            result[key] = _dedup_result_envelopes(item[key])
    if entry['kind'] == 'McpToolCall':
        result['arguments'] = item.get('arguments', {})
    return result


def _pointer_part(value: str) -> str:
    return value.replace('~', '~0').replace('/', '~1')


def _inline_evidence(entry: dict, value, pointer: str = '', snapshot_sha256: str = ''):
    # Native messages and visible reasoning are already small on real sources;
    # long tool inputs/outputs become explicit expandable evidence, not silent
    # truncation. Hashes address original UTF-8 values, not their JSON escaping.
    if isinstance(value, str) and len(value) > MAX_INLINE_TEXT_CHARS:
        return {'evidence_ref': {'session_id': entry['session_id'], 'snapshot_sha256': snapshot_sha256,
                    'item_id': entry['item_id'], 'field': pointer,
                    'sha256': hashlib.sha256(value.encode()).hexdigest(),
                    'chars': len(value), 'bytes': len(value.encode())},
                'head': value[:INLINE_HEAD_CHARS], 'tail': value[-INLINE_TAIL_CHARS:],
                'omitted_chars': len(value) - INLINE_HEAD_CHARS - INLINE_TAIL_CHARS}
    if isinstance(value, dict):
        return {key: _inline_evidence(entry, child, pointer + '/' + _pointer_part(key), snapshot_sha256)
                for key, child in value.items()}
    if isinstance(value, list):
        return [_inline_evidence(entry, child, pointer + '/' + str(index), snapshot_sha256) for index, child in enumerate(value)]
    return value


def _detail_projection(entry: dict, snapshot_sha256: str = '') -> dict:
    body = _detailed_item(entry)
    if entry['kind'] in ('CommandExecution', 'McpToolCall', 'FileChange', 'Extension'):
        return _inline_evidence(entry, body, snapshot_sha256=snapshot_sha256)
    return body


def _text_blocks(text: str) -> list[str]:
    """Exact bounded blocks for sharing repeated parts of different outputs."""
    blocks, pending = [], ''
    for line in text.splitlines(keepends=True):
        pending += line
        while len(pending) >= 512:
            blocks.append(pending[:512])
            pending = pending[512:]
        if len(pending) >= 256 and hashlib.sha256(line.encode()).digest()[0] & 7 == 0:
            blocks.append(pending)
            pending = ''
    if pending:
        blocks.append(pending)
    return blocks


def render(snapshot: dict, detail: bool = False) -> str:
    """Render one canonical timeline; use render_many for a root/child forest."""
    return render_many([snapshot], detail=detail)


def render_many(snapshots: list[dict], detail: bool = False) -> str:
    """Render exact sessions with one shared pool for repeated substantive blobs.

    Compact contains no outputs or diffs. Detailed adds output/diff evidence with bounded head/tail previews and exact
    field handles. Shared exact text blocks appear once. Stable handles always
    lead back to the complete native item or requested field.
    """
    if type(detail) is not bool:
        raise ValueError('detail must be a boolean.')
    if not isinstance(snapshots, list) or len(snapshots) > 64:
        raise ValueError('Render at most 64 exact snapshots.')
    rows = []
    counts = Counter()
    if detail:
        def count(value):
            if isinstance(value, str):
                for block in _text_blocks(value):
                    if len(block) >= 256:
                        counts[block] += 1
            elif isinstance(value, dict):
                for child in value.values():
                    count(child)
            elif isinstance(value, list):
                for child in value:
                    count(child)
        for snapshot in snapshots:
            for entry in snapshot['items']:
                count(_detail_projection(entry, snapshot['sha256']))
    emitted = set()
    def dedup(value):
        if isinstance(value, str):
            blocks = _text_blocks(value)
            if not any(counts[block] > 1 and len(block) >= 256 for block in blocks):
                return value
            parts = []
            for block in blocks:
                if len(block) < 256 or counts[block] <= 1:
                    parts.append(block)
                    continue
                digest = hashlib.sha256(block.encode()).hexdigest()
                if digest in emitted:
                    parts.append({'blob_ref': 'sha256:' + digest, 'chars': len(block)})
                else:
                    emitted.add(digest)
                    parts.append({'blob_id': 'sha256:' + digest, 'text': block})
            return parts[0] if len(parts) == 1 and isinstance(parts[0], dict) else {'text_parts': parts, 'chars': len(value)}
        if isinstance(value, dict):
            return {key: dedup(child) for key, child in value.items()}
        if isinstance(value, list):
            return [dedup(child) for child in value]
        return value
    for snapshot in snapshots:
        rows.extend([f"Codex native items · {snapshot['session_id']} · {len(snapshot['items'])} items",
                     'Native snapshot: ' + _json({'schema': snapshot['schema'], 'schema_version': 1,
                         'session_id': snapshot['session_id'], 'sha256': snapshot['sha256'],
                         'mode': 'detailed' if detail else 'compact', 'item_count': len(snapshot['items']),
                         'source_sha256': snapshot['source']['sha256'], 'source_kind': snapshot['source']['kind']})])
        settings = list(snapshot.get('settings', []))
        active_settings = {}
        active_turn = object()
        for entry in snapshot['items']:
            while settings and settings[0]['record'] <= entry['first_record']:
                changed = settings.pop(0)['values']
                active_settings.update(changed)
                rows.append('Settings: ' + _json(changed))
            body = _detail_projection(entry, snapshot['sha256']) if detail else _compact_item(entry)
            # cwd is inherited explicitly from the last settings transition.
            cwd = body.pop('cwd', None)
            if cwd is not None and active_settings.get('cwd') != cwd:
                active_settings['cwd'] = cwd
                rows.append('Settings: ' + _json({'cwd': cwd}))
            if entry['turn_id'] != active_turn:
                active_turn = entry['turn_id']
                rows.append('Native turn: ' + _json({'turn_id': active_turn}))
            # One row is both the reader's representation and the typed boundary.
            if 'kind' in body:
                body['native_kind'] = body.pop('kind')
            rows.append('Native item: ' + _json({'native_id': entry['item_id'],
                'kind': entry['kind'], 'source_record_index': entry['first_record'],
                **(dedup(body) if detail else body)}))
        for setting in settings:
            rows.append('Settings: ' + _json(setting['values']))
    return '\n'.join(rows) + '\n'
