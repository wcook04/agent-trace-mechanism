"""Explicit-file access to captured records, immutable views and bounded changes."""
from collections import OrderedDict
from contextlib import contextmanager
from threading import RLock
from .recordings import fixed_selection, recording_id, file_version
import copy
import hashlib
import io
import json
import os
from . import codex_native as native
from .parser import parse_claude_session, parse_codex_session
from .views import render


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}.')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class TranscriptInput:
    """A checked capture for the original parsers, with physical line numbers preserved."""
    def __init__(self, path, raw, stat, session_id, provider):
        self.path, self.file_stat = path, stat
        self.raw, self.session_id, self.provider = raw, session_id, provider
        self.warnings, self.finals = {}, {}

    def iter_lines(self):
        observed = set()
        for index, line in enumerate(io.BytesIO(self.raw)):
            issue = None
            try:
                if len(line) > native.MAX_RECORD_BYTES:
                    issue = 'oversized records'
                    raise ValueError('Record exceeds the source limit')
                record = json.loads(line)
                if not isinstance(record, dict) or any(
                    not isinstance(record.get(key) or {}, dict) for key in ('payload', 'message')
                ):
                    raise ValueError('Invalid record shape')
                payload = record.get('payload') or {}
                message = record.get('message') or {}
                if self.provider == 'claude' and record.get('sessionId') is not None:
                    observed.add(record['sessionId'])
                final = None
                if record.get('type') == 'event_msg' and payload.get('type') == 'task_complete':
                    final = payload.get('last_agent_message')
                if record.get('type') == 'assistant' and message.get('stop_reason') in ('end_turn', 'stop_sequence'):
                    content = message.get('content')
                    final = content if isinstance(content, str) else '\n'.join(
                        block['text'] for block in content or [] if isinstance(block, dict)
                        and block.get('type') == 'text' and isinstance(block.get('text'), str))
                if isinstance(final, str) and final.strip():
                    self.finals[index] = final
            except (ValueError, RecursionError, TypeError):
                issue = issue or ('malformed records' if line.endswith(b'\n') else 'pending records')
                self.warnings[issue] = self.warnings.get(issue, 0) + 1
                line = b'\n'
            yield line
        if self.provider == 'claude' and observed != {self.session_id}:
            raise ValueError('Claude source session identity does not match the registered session.')

    def stat(self):
        return self.file_stat

    @contextmanager
    def open(self):
        yield self.iter_lines()

    def __str__(self):
        return str(self.path)


def captured_turns(path, session_id, provider, snapshot=None):
    with path.open('rb') as stream:
        raw = stream.read(native.MAX_SOURCE_BYTES + 1)
        if len(raw) > native.MAX_SOURCE_BYTES:
            raise ValueError('Session exceeds the bounded source size.')
        stat = os.fstat(stream.fileno())
    if snapshot:
        if hashlib.sha256(raw).hexdigest() != snapshot['source']['sha256']:
            raise ValueError('The conversation changed during capture. Try again.')
        if b'task_started' not in raw:
            return [], {}, {}
    source = TranscriptInput(path, raw, stat, session_id, provider)
    parse = parse_codex_session if provider == 'codex' else parse_claude_session
    return parse(source), source.warnings, source.finals


def render_codex_context(snapshots, paths, *, detail, turns=0, closeout=False, require_readable=False):
    """Render the same selected evidence for local browsing and registered MCP reads."""
    native_sessions, transcripts = [], []
    for snapshot in snapshots:
        sid = snapshot['session_id']
        items = snapshot['items']
        parsed, _, recorded_finals = captured_turns(paths[sid], sid, 'codex', snapshot)
        legacy = parsed
        if turns:
            # Both readers expose physical record positions. Group by turn ID,
            # then select by first appearance across both recording formats.
            positions = {}
            for item in items:
                if not item['turn_id']:
                    raise ValueError('Recorded items lack turn IDs. Choose a full-thread scope.')
                positions.setdefault(item['turn_id'], item['first_record'])
            for turn in legacy:
                first = min(turn.source_record_indices) + 1
                positions[turn.turn_id] = min(first, positions.get(turn.turn_id, first))
            selected = set(sorted(positions, key=positions.get)[-turns:])
            items = [i for i in items if i['turn_id'] in selected]
            legacy = [t for t in legacy if t.turn_id in selected]
        legacy = [t for t in legacy if t.prompt_text or t.assistant_text or t.tool_events]
        if require_readable and not (items or legacy):
            raise ValueError(f"No readable content in the selected scope for {sid}.")
        if closeout:
            finals = [(i['first_record'], native._message_text(i['item'])) for i in items
                      if i['kind'] == 'AgentMessage' and i['item'].get('phase') == 'final_answer'
                      and i['source_refs'][-1]['event_type'] == 'item_completed']
            finals.extend((index + 1, recorded_finals[index]) for t in legacy
                          for index in t.source_record_indices if index in recorded_finals)
            if not finals:
                raise ValueError('No completed assistant answer recorded in this scope.')
            return max(finals)[1], 'closeout'
        if items:
            native_sessions.append(dict(snapshot, items=items))
        if legacy:
            rendered = render(legacy, detail=detail)
            if len(snapshots) > 1 or items:
                rendered = 'Transcript records · ' + sid + '\n' + rendered
            transcripts.append(rendered)
    blocks = [native.render_many(native_sessions, detail=detail)] if native_sessions else []
    blocks.extend(transcripts)
    mode = 'mixed' if native_sessions and transcripts else 'native' if native_sessions else 'legacy'
    return '\n\n'.join(blocks), mode


def selected_recording_text(path, provider, sid, label, detail, multiple):
    """Render one explicitly chosen file. Never resolve a sibling by its session ID."""
    issues = []
    if provider == 'codex':
        snapshot = native.load_rollout(path, session_id=sid)
        text, _ = render_codex_context([snapshot], {sid: path}, detail=detail, require_readable=True)
        issues = [f'{name}: {count}' for name, count in snapshot['diagnostics'].items()
                  if count and name in ('pending_records', 'malformed_records', 'oversized_records', 'identity_mismatches')]
    else:
        turns, warnings, _ = captured_turns(path, sid, 'claude')
        text = render(turns, detail=detail)
        issues = [f'{name}: {count}' for name, count in warnings.items()]
    if not text:
        raise ValueError(f'No readable content in {label}.')
    return (f'Session: {label}\n{text}' if multiple else text), issues


class SnapshotStore:
    """FIFO immutable captures with an exact serialized payload budget."""
    def __init__(self, max_count=32, max_bytes=64 << 20):
        self.items = OrderedDict()
        self.max_count, self.max_bytes = max_count, max_bytes
        self.size = 0
        self.lock = RLock()

    def __setitem__(self, key, value):
        with self.lock:
            if key in self.items:
                return
            blob = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()
            if len(blob) > self.max_bytes:
                raise ValueError('Capture exceeds the snapshot retention budget. Choose a smaller scope.')
            while self.items and (len(self.items) >= self.max_count or self.size + len(blob) > self.max_bytes):
                self.size -= len(self.items.popitem(last=False)[1])
            self.items[key] = blob
            self.size += len(blob)

    def get(self, key):
        with self.lock:
            blob = self.items.get(key)
        return json.loads(blob) if blob is not None else None

    def __contains__(self, key):
        return key in self.items

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise ValueError('Snapshot expired. Capture the selected recordings again.')
        return value


class AgentTools:
    def __init__(self, entries, entry_loader=None):
        self.entries = list(entries)
        self.entry_loader = entry_loader
        self.snapshots = SnapshotStore()
        self.native_snapshots = SnapshotStore()
        self.native_items = SnapshotStore()
        self.delta_snapshots = SnapshotStore()

    def _refresh_entries(self):
        if self.entry_loader is None:
            return
        old = {(r['provider'], r['session_id']): r for r in self.entries}
        entries = list(self.entry_loader())
        for row in entries:
            previous = old.get((row['provider'], row['session_id']), {})
            if (row.get('source_available') is False and previous.get('parent_edge_verified')
                    and row.get('path') == previous.get('path')
                    and row.get('parent_session_id') == previous.get('parent_session_id')):
                row['parent_edge_verified'] = True
        self.entries = entries

    def _entry(self, provider, session_id):
        rows = [r for r in self.entries if (r['provider'], r['session_id']) == (provider, session_id)]
        recorded_matches = [r for r in self.entries if r['provider'] == provider and r.get('recorded_id', r['session_id']) == session_id]
        if len(rows) != 1 or len(recorded_matches) > 1 or provider not in ('codex', 'claude'):
            raise ValueError('Choose one registered provider and session ID. For overlapping IDs use read_selected_context with recording IDs from search_trace_threads.')
        if rows[0].get('source_unavailable_reason') == 'registered_file_replaced':
            raise ValueError('Registered file replaced. Register the intended file again.')
        return rows[0]

    def search_trace_threads(self, query):
        self._refresh_entries()
        terms = query.casefold().split()
        return [{key: row[key] for key in ('provider', 'session_id', 'title', 'recording_id', 'recorded_id', 'parent_session_id') if key in row}
                for row in self.entries if all(term in
                f"{row['provider']} {row['session_id']} {row['title']}".casefold() for term in terms)]

    def read_selected_context(self, recording_ids, scope='full_thread', limit=24000):
        _integer(limit, 'limit', 1, 48000)
        if (scope not in ('full_thread', 'full_thread_concise') or not isinstance(recording_ids, list)
                or not 1 <= len(recording_ids) <= 64 or not all(isinstance(x, str) for x in recording_ids)
                or len(set(recording_ids)) != len(recording_ids)):
            raise ValueError('Choose up to 64 distinct registered recording IDs and a valid scope.')
        self._refresh_entries()
        allowed = {r.get('recording_id'): r for r in self.entries}
        if any(ref not in allowed or allowed[ref].get('source_available') is False for ref in recording_ids):
            raise ValueError('A selected recording is unregistered or unavailable.')
        rows = [allowed[ref] for ref in recording_ids]
        pieces, warnings = [], []
        with fixed_selection([r['path'] for r in rows]) as versions:
            for r in rows:
                sid = r.get('recorded_id', r['session_id'])
                if recording_id(r['path'], r['provider'], sid) != r['recording_id']:
                    raise ValueError('Selected recording changed. Register the intended file again.')
                piece, issues = selected_recording_text(r['path'], r['provider'], sid, r['session_id'],
                                                       scope == 'full_thread', len(rows) > 1)
                pieces.append(piece)
                warnings.extend(issues)
        text = '\n\n'.join(pieces)
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.snapshots[digest] = text
        return {**self.read_trace_page(digest, 0, limit), 'recording_ids': recording_ids, 'warnings': warnings,
                'source_versions': [versions[r['path']] for r in rows], 'consistency': 'selected_versions_checked'}

    def _remember_bundle(self, bundle):
        # Filesystem locations and platform-specific errors do not define records.
        identity = {key: bundle[key] for key in ('schema', 'root_session_id', 'include_children',
                                                 'edges', 'availability')}
        identity['sessions'] = [{'session_id': s['session_id'], 'sha256': s['sha256']}
                                for s in bundle['sessions']]
        digest = _digest(identity)
        self.native_snapshots[digest] = bundle
        for session in bundle['sessions']:
            self.native_items[session['sha256']] = session
        return digest, bundle

    def _capture(self, provider, session_id, include_children=False):
        if provider != 'codex':
            raise ValueError('Native item queries require Codex JSONL records; SQLite is library-only.')
        if type(include_children) is not bool:
            raise ValueError('include_children must be a boolean.')
        self._refresh_entries()
        root = self._entry(provider, session_id)
        selected, seen = [root], {session_id}
        if include_children:
            for parent in selected:
                for child in sorted(self.entries, key=lambda row: row['session_id']):
                    if (child['provider'] == provider and child.get('parent_session_id') == parent['session_id']
                            and child['session_id'] not in seen):
                        selected.append(child)
                        seen.add(child['session_id'])
                        if len(selected) > 64:
                            raise ValueError('Select a tree of at most 64 sessions.')
        if any(sum(r['provider'] == provider and r['session_id'] == selected_row['session_id'] for r in self.entries) != 1 for selected_row in selected):
            raise ValueError('Tree has ambiguous sessions. Use read_selected_context with explicit recording IDs.')
        initial = {}
        for row in selected:
            if row.get('source_available') is False:
                continue
            try:
                initial[row['path']] = file_version(row['path'])
            except OSError:
                continue  # The availability receipt below identifies unavailable children.
        if sum(v[2] for v in initial.values()) > native.MAX_SOURCE_BYTES:
            raise ValueError('Choose a tree with at most 256 MiB of source data.')
        sessions, availability = [], []
        for row in selected:
            if row is not root and row.get('source_available') is False:
                availability.append({'session_id': row['session_id'], 'status': 'unavailable',
                                     'reason': row.get('source_unavailable_reason') or 'source_unreadable'})
                continue
            try:
                snapshot = native.load_rollout(row['path'], session_id=row['session_id'])
            except (OSError, ValueError, UnicodeError) as exc:
                if row is root:
                    raise ValueError('The registered root source could not be captured.') from exc
                reason = ('source_missing' if isinstance(exc, FileNotFoundError) else
                          'source_unreadable' if isinstance(exc, OSError) else 'invalid_source')
                availability.append({'session_id': row['session_id'], 'status': 'unavailable', 'reason': reason})
                continue
            sessions.append(snapshot)
            availability.append({'session_id': row['session_id'], 'status': 'available'})
        edges = [{'parent': r['parent_session_id'], 'child': r['session_id'],
                  'recorded': bool(r.get('parent_edge_verified', False))}
                 for r in selected if r.get('parent_session_id') in seen]
        for path, version in initial.items():
            if file_version(path) != version:
                raise ValueError('A registered source changed during capture. Try again.')
        return self._remember_bundle({'schema': 'native_trace_bundle_v2', 'root_session_id': session_id,
            'include_children': include_children, 'sessions': sessions, 'edges': edges, 'availability': availability})

    def _bundle(self, provider, session_id, digest='', include_children=False):
        if provider != 'codex':
            raise ValueError('Native item queries require Codex records.')
        if digest:
            bundle = self.native_snapshots.get(digest)
            if bundle is None:
                core = self.native_items.get(digest)
                if core is not None and core['session_id'] == session_id:
                    return self._remember_bundle({'schema': 'native_trace_bundle_v2',
                        'root_session_id': session_id, 'include_children': False, 'sessions': [core],
                        'edges': [], 'availability': [{'session_id': session_id, 'status': 'available'}]})
            if bundle is None or bundle['root_session_id'] != session_id:
                raise ValueError('Unknown record snapshot for this root session. Use snapshot_sha256, not text_sha256.')
            return digest, bundle
        return self._capture(provider, session_id, include_children)

    @staticmethod
    def _availability(bundle):
        return {'partial': (any(r['status'] != 'available' for r in bundle['availability'])
                            or any(not edge['recorded'] for edge in bundle['edges'])),
                'availability': copy.deepcopy(bundle['availability']),
                'native_item_coverage': {
                    'native_sessions': [s['session_id'] for s in bundle['sessions'] if s['has_native_items']],
                    'legacy_sessions': [s['session_id'] for s in bundle['sessions'] if not s['has_native_items']],
                    'changes_track': 'native_items_only'},
                'consistency': 'assembled_sequentially', 'snapshot_lifetime': 'bounded_process_cache'}

    def search_trace_items(self, provider, session_id, query='', kind='', failures_only=False,
                           include_children=False, snapshot_sha256='', limit=20, offset=0):
        _integer(limit, 'limit', 1, 100)
        _integer(offset, 'offset', 0, 1000000)
        if type(include_children) is not bool:
            raise ValueError('include_children must be a boolean.')
        digest, bundle = self._bundle(provider, session_id, snapshot_sha256, include_children)
        items, total, remaining = [], 0, offset
        for snapshot in bundle['sessions']:
            result = native.search(snapshot, query, [kind] if kind else None, failures_only, 1)
            count = result['total_matches']
            total += count
            if remaining >= count:
                remaining -= count
                continue
            if len(items) < limit:
                page = native.search(snapshot, query, [kind] if kind else None, failures_only,
                                     limit - len(items), remaining)
                items.extend(page['items'])
            remaining = 0
        end = min(total, offset + len(items))
        return {'snapshot_sha256': digest, 'snapshot_kind': 'native_bundle', 'root_session_id': session_id,
                'sessions': [native.summary(s) for s in bundle['sessions']], 'edges': copy.deepcopy(bundle['edges']),
                'items': copy.deepcopy(items), 'total_matches': total, 'offset': offset,
                'offset_unit': 'matching_items', 'next_offset': end if end < total else None,
                **self._availability(bundle)}

    def read_trace_item(self, provider, session_id, item_id, snapshot_sha256='', offset=0, limit=24000, field=''):
        if provider != 'codex':
            raise ValueError('Native item queries require Codex records.')
        if snapshot_sha256:
            bundle = self.native_snapshots.get(snapshot_sha256)
            if bundle is None:
                snapshot = self.native_items.get(snapshot_sha256)
                if snapshot is None:
                    raise ValueError('Unknown or expired native snapshot.')
                bundle, kind = {'sessions': [snapshot]}, 'native_core'
            else:
                kind = 'native_bundle'
        else:
            snapshot_sha256, bundle = self._capture(provider, session_id)
            kind = 'native_bundle'
        snapshot = next((s for s in bundle['sessions'] if s['session_id'] == session_id), None)
        if snapshot is None:
            raise ValueError('This session is not available in the selected snapshot.')
        return {**copy.deepcopy(native.read_item(snapshot, item_id, offset, limit, field=field)),
                'snapshot_sha256': snapshot_sha256, 'snapshot_kind': kind}

    def read_trace_changes(self, provider, session_id, since_sha256, include_children=False,
                           limit=20, offset=0, snapshot_sha256=''):
        _integer(limit, 'limit', 1, 100)
        _integer(offset, 'offset', 0, 1000000)
        if type(include_children) is not bool:
            raise ValueError('include_children must be a boolean.')
        before_digest, before = self._bundle(provider, session_id, since_sha256)
        if before['include_children'] != include_children:
            raise ValueError('Use the same include_children selection as the earlier snapshot.')
        if offset and not snapshot_sha256:
            raise ValueError('Continue changes with the returned snapshot_sha256 and next_offset.')
        digest, after = self._bundle(provider, session_id, snapshot_sha256, include_children)
        if after['include_children'] != include_children:
            raise ValueError('Use the same include_children selection for both snapshots.')
        key = (before_digest, digest)
        if key not in self.delta_snapshots:
            old = {s['session_id']: s for s in before['sessions']}
            flat = []
            for snapshot in after['sessions']:
                sid = snapshot['session_id']
                previous = old.pop(sid, {**snapshot, 'items': [], 'sha256': None})
                delta = native.diff_snapshots(previous, snapshot)
                for change in ('added', 'updated', 'removed'):
                    flat.extend({'session_id': sid, 'change': change, 'item': item} for item in delta[change])
            selected = {row['session_id'] for row in after['availability']}
            removed = sorted(set(old) - selected)
            flat.extend({'session_id': sid, 'change': 'session_removed'} for sid in removed)
            prior = {r['session_id']: r for r in before['availability']}
            availability_changes = [r for r in after['availability'] if prior.get(r['session_id']) != r]
            flat.extend({'session_id': r['session_id'], 'change': 'availability', 'availability': r}
                        for r in availability_changes)
            self.delta_snapshots[key] = flat, removed, availability_changes
        flat, removed, availability_changes = self.delta_snapshots[key]
        page = flat[offset:offset + limit]
        grouped = {}
        for row in page:
            if 'item' in row:
                group = grouped.setdefault(row['session_id'], {'session_id': row['session_id'],
                    'added': [], 'updated': [], 'removed': []})
                group[row['change']].append(row['item'])
        end = min(len(flat), offset + len(page))
        return {'snapshot_sha256': digest, 'snapshot_kind': 'native_bundle', 'since_sha256': before_digest,
                'items': copy.deepcopy(page), 'changes': copy.deepcopy(list(grouped.values())),
                'total_changes': len(flat), 'offset': offset, 'offset_unit': 'change_records',
                'next_offset': end if end < len(flat) else None, 'removed_sessions': removed,
                'availability_changes': copy.deepcopy(availability_changes), 'edges': copy.deepcopy(after['edges']),
                **self._availability(after)}

    def read_chat_context(self, provider, session_id, scope='full_thread_concise', limit=24000,
                          include_children=False):
        _integer(limit, 'limit', 1, 48000)
        if scope not in ('full_thread_concise', 'full_thread'):
            raise ValueError('Choose compact or detailed full-thread scope.')
        if type(include_children) is not bool:
            raise ValueError('include_children must be a boolean.')
        metadata = {}
        if provider == 'codex':
            digest, bundle = self._capture(provider, session_id, include_children)
            paths = {r['session_id']: r['path'] for r in self.entries if r['provider'] == provider}
            text, format_name = render_codex_context(bundle['sessions'], paths, detail=scope == 'full_thread')
            metadata = {'snapshot_kind': 'native_bundle' if format_name != 'legacy' else 'text',
                        'include_children': include_children, 'context_format': format_name,
                        'edges': copy.deepcopy(bundle['edges']), **self._availability(bundle)}
            if format_name != 'legacy':
                metadata['snapshot_sha256'] = digest
                if bundle['sessions'][0]['has_native_items']:
                    metadata['native_snapshot_sha256'] = bundle['sessions'][0]['sha256']
        else:
            self._refresh_entries()
            row = self._entry(provider, session_id)
            if include_children:
                group = [row, *sorted((r for r in self.entries if r['provider'] == provider and
                    r.get('parent_session_id') == session_id), key=lambda r: r['session_id'])]
                if all(r.get('recording_id') for r in group):
                    return self.read_selected_context([r['recording_id'] for r in group], scope, limit)
            parsed, warnings, _ = captured_turns(row['path'], row.get('recorded_id', session_id), provider)
            text = render(parsed, detail=scope == 'full_thread')
            if warnings:
                metadata['record_warnings'] = warnings
        text_digest = hashlib.sha256(text.encode()).hexdigest()
        self.snapshots[text_digest] = text
        return {'provider': provider, 'session_id': session_id, 'scope': scope, **metadata,
                **self.read_trace_page(text_digest, 0, limit)}

    def read_trace_page(self, sha256, offset=0, limit=24000):
        _integer(offset, 'offset', 0, 268435456)
        _integer(limit, 'limit', 1, 48000)
        if sha256 not in self.snapshots:
            raise ValueError('Unknown or expired text snapshot. Use text_sha256 from read_chat_context.')
        text = self.snapshots[sha256]
        if offset > len(text):
            raise ValueError('Offset is beyond the snapshot.')
        end = min(offset + limit, len(text))
        return {'sha256': sha256, 'text_sha256': sha256, 'text': text[offset:end],
                'offset': offset, 'offset_unit': 'unicode_characters',
                'next_offset': end if end < len(text) else None, 'total_chars': len(text)}
