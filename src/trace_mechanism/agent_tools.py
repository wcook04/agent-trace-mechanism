"""Explicit-file access to captured records, immutable views and bounded changes."""
import copy
import hashlib
import json
from . import codex_native as native
from .parser import parse_claude_session, parse_codex_session
from .views import render


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}.')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class AgentTools:
    def __init__(self, entries, entry_loader=None):
        self.entries = list(entries)
        self.entry_loader = entry_loader
        self.snapshots = {}
        self.native_snapshots = {}
        self.native_items = {}
        self.delta_snapshots = {}

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
        if len(rows) != 1 or provider not in ('codex', 'claude'):
            raise ValueError('Choose one registered provider and session ID.')
        return rows[0]

    def search_trace_threads(self, query):
        self._refresh_entries()
        terms = query.casefold().split()
        return [{key: row[key] for key in ('provider', 'session_id', 'title')}
                for row in self.entries if all(term in
                f"{row['provider']} {row['session_id']} {row['title']}".casefold() for term in terms)]

    def _remember_bundle(self, bundle):
        # Filesystem locations and platform-specific errors do not define records.
        identity = {key: bundle[key] for key in ('schema', 'root_session_id', 'include_children',
                                                 'edges', 'availability')}
        identity['sessions'] = [{'session_id': s['session_id'], 'sha256': s['sha256']}
                                for s in bundle['sessions']]
        digest = _digest(identity)
        self.native_snapshots[digest] = bundle
        self.native_items.update({s['sha256']: s for s in bundle['sessions']})
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
                for child in self.entries:
                    if (child['provider'] == provider and child.get('parent_session_id') == parent['session_id']
                            and child['session_id'] not in seen):
                        selected.append(child)
                        seen.add(child['session_id'])
                        if len(selected) > 64:
                            raise ValueError('Select a tree of at most 64 sessions.')
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
                'consistency': 'assembled_sequentially', 'snapshot_lifetime': 'server_process'}

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
                    raise ValueError('Unknown native snapshot.')
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
            if any(s['has_native_items'] for s in bundle['sessions']):
                native_sessions = [s for s in bundle['sessions'] if s['has_native_items']]
                text = native.render_many(native_sessions, detail=scope == 'full_thread')
                legacy = [s for s in bundle['sessions'] if not s['has_native_items']]
                by_id = {r['session_id']: r for r in self.entries if r['provider'] == provider}
                for snapshot in legacy:
                    text += '\nLegacy session: ' + snapshot['session_id'] + '\n' + render(
                        parse_codex_session(by_id[snapshot['session_id']]['path']), detail=scope == 'full_thread')
                format_name = 'mixed' if legacy else 'native'
            else:
                by_id = {r['session_id']: r for r in self.entries if r['provider'] == provider}
                text = '\n\n'.join(render(parse_codex_session(by_id[s['session_id']]['path']),
                                          detail=scope == 'full_thread') for s in bundle['sessions'])
                format_name = 'legacy'
            metadata = {'snapshot_kind': 'native_bundle' if format_name != 'legacy' else 'text',
                        'include_children': include_children, 'context_format': format_name,
                        'edges': copy.deepcopy(bundle['edges']), **self._availability(bundle)}
            if format_name != 'legacy':
                metadata['snapshot_sha256'] = digest
                if bundle['sessions'][0]['has_native_items']:
                    metadata['native_snapshot_sha256'] = bundle['sessions'][0]['sha256']
        else:
            if include_children:
                raise ValueError('Registered child traversal currently requires Codex records.')
            self._refresh_entries()
            row = self._entry(provider, session_id)
            observed = set()
            with row['path'].open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict) and record.get('sessionId'):
                        observed.add(record['sessionId'])
            if observed != {session_id}:
                raise ValueError('Claude source session identity does not match the registered session.')
            text = render(parse_claude_session(row['path']), detail=scope == 'full_thread')
        text_digest = hashlib.sha256(text.encode()).hexdigest()
        self.snapshots[text_digest] = text
        return {'provider': provider, 'session_id': session_id, 'scope': scope, **metadata,
                **self.read_trace_page(text_digest, 0, limit)}

    def read_trace_page(self, sha256, offset=0, limit=24000):
        _integer(offset, 'offset', 0, 268435456)
        _integer(limit, 'limit', 1, 48000)
        if sha256 not in self.snapshots:
            raise ValueError('Unknown text snapshot. Use text_sha256 from read_chat_context.')
        text = self.snapshots[sha256]
        if offset > len(text):
            raise ValueError('Offset is beyond the snapshot.')
        end = min(offset + limit, len(text))
        return {'sha256': sha256, 'text_sha256': sha256, 'text': text[offset:end],
                'offset': offset, 'offset_unit': 'unicode_characters',
                'next_offset': end if end < len(text) else None, 'total_chars': len(text)}
