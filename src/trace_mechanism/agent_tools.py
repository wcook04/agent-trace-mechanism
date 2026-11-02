"""Explicit-file access to native items, immutable views and incremental changes."""
import hashlib
import json
from . import codex_native as native
from .parser import parse_claude_session, parse_codex_session
from .views import render


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}.')


class AgentTools:
    def __init__(self, entries):
        self.entries = list(entries)
        self.snapshots = {}
        self.native_snapshots = {}
        self.native_items = {}

    def _entry(self, provider, session_id):
        rows = [r for r in self.entries if (r['provider'], r['session_id']) == (provider, session_id)]
        if len(rows) != 1 or provider not in ('codex', 'claude'):
            raise ValueError('Choose one registered provider and session ID.')
        return rows[0]

    def search_trace_threads(self, query):
        terms = query.casefold().split()
        return [{key: row[key] for key in ('provider', 'session_id', 'title')}
                for row in self.entries if all(term in
                f"{row['provider']} {row['session_id']} {row['title']}".casefold() for term in terms)]

    def _capture(self, provider, session_id, include_children=False):
        if provider != 'codex':
            raise ValueError('Native item queries require Codex records.')
        if type(include_children) is not bool:
            raise ValueError('include_children must be a boolean.')
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
        sessions = [native.load_rollout(row['path'], row['session_id']) for row in selected]
        self.native_items.update({s['sha256']: s for s in sessions})
        bundle = {'schema': 'native_trace_bundle_v1', 'root_session_id': session_id,
                  'include_children': include_children, 'sessions': sessions,
                  'edges': [{'parent': r['parent_session_id'], 'child': r['session_id']}
                            for r in selected if r.get('parent_session_id') in seen]}
        encoded = json.dumps(bundle, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        self.native_snapshots[digest] = bundle
        return digest, bundle

    def _bundle(self, provider, session_id, digest='', include_children=False):
        self._entry(provider, session_id)
        if provider != 'codex':
            raise ValueError('Native item queries require Codex records.')
        if digest:
            bundle = self.native_snapshots.get(digest)
            if bundle is None or bundle['root_session_id'] != session_id:
                raise ValueError('Unknown snapshot for this root session.')
            return digest, bundle
        return self._capture(provider, session_id, include_children)

    def search_trace_items(self, provider, session_id, query='', kind='', failures_only=False,
                           include_children=False, snapshot_sha256='', limit=20, offset=0):
        _integer(limit, 'limit', 1, 100)
        _integer(offset, 'offset', 0, 1000000)
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
        return {'snapshot_sha256': digest, 'root_session_id': session_id,
                'sessions': [native.summary(s) for s in bundle['sessions']], 'edges': bundle['edges'],
                'items': items, 'total_matches': total, 'offset': offset,
                'next_offset': end if end < total else None}

    def read_trace_item(self, provider, session_id, item_id, snapshot_sha256='', offset=0, limit=24000, field=''):
        self._entry(provider, session_id)
        if provider != 'codex':
            raise ValueError('Native item queries require Codex records.')
        if snapshot_sha256:
            bundle = self.native_snapshots.get(snapshot_sha256)
            if bundle is None:
                snapshot = self.native_items.get(snapshot_sha256)
                if snapshot is None:
                    raise ValueError('Unknown native snapshot.')
                bundle = {'sessions': [snapshot]}
        else:
            snapshot_sha256, bundle = self._capture(provider, session_id)
        snapshot = next((s for s in bundle['sessions'] if s['session_id'] == session_id), None)
        if snapshot is None:
            raise ValueError('This session is not in the selected snapshot.')
        return {**native.read_item(snapshot, item_id, offset, limit, field=field), 'snapshot_sha256': snapshot_sha256}

    def read_trace_changes(self, provider, session_id, since_sha256, include_children=False):
        _, before = self._bundle(provider, session_id, since_sha256)
        if before['include_children'] != include_children:
            raise ValueError('Use the same include_children selection as the earlier snapshot.')
        digest, after = self._capture(provider, session_id, include_children)
        old = {s['session_id']: s for s in before['sessions']}
        changes = []
        for snapshot in after['sessions']:
            sid = snapshot['session_id']
            if sid in old:
                diff = native.diff_snapshots(old.pop(sid), snapshot)
            else:
                diff = native.diff_snapshots({**snapshot, 'items': [], 'sha256': None}, snapshot)
            if any(diff[key] for key in ('added', 'updated', 'removed')):
                changes.append({'session_id': sid, **diff})
        return {'snapshot_sha256': digest, 'since_sha256': since_sha256, 'changes': changes,
                'removed_sessions': sorted(old), 'edges': after['edges']}

    def read_chat_context(self, provider, session_id, scope='full_thread_concise', limit=24000):
        row = self._entry(provider, session_id)
        if scope not in ('full_thread_concise', 'full_thread'):
            raise ValueError('Choose compact or detailed full-thread scope.')
        snapshot = native.load_rollout(row['path']) if provider == 'codex' else None
        if snapshot and snapshot['items'] and snapshot['session_id'] != session_id:
            raise ValueError('Requested session ID does not match native records.')
        if snapshot and snapshot['items']:
            self.native_items[snapshot['sha256']] = snapshot
            text = native.render(snapshot, detail=scope == 'full_thread')
        else:
            parser = parse_codex_session if provider == 'codex' else parse_claude_session
            text = render(parser(row['path']), detail=scope == 'full_thread')
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.snapshots[digest] = text
        return {'provider': provider, 'session_id': session_id, 'scope': scope,
                **({'native_snapshot_sha256': snapshot['sha256']} if snapshot and snapshot['items'] else {}),
                **self.read_trace_page(digest, 0, limit)}

    def read_trace_page(self, sha256, offset=0, limit=24000):
        _integer(offset, 'offset', 0, 268435456)
        _integer(limit, 'limit', 1, 48000)
        if sha256 not in self.snapshots:
            raise ValueError('Unknown snapshot.')
        text = self.snapshots[sha256]
        if offset > len(text):
            raise ValueError('Offset is beyond the snapshot.')
        end = min(offset + limit, len(text))
        return {'sha256': sha256, 'text': text[offset:end],
                'next_offset': end if end < len(text) else None, 'total_chars': len(text)}
