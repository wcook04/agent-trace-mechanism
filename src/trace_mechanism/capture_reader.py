#!/usr/bin/env python3
"""Read an Agent Trace capture without Agent Trace. Python 3.9+ standard library only.

A capture is a ZIP of exactly selected Codex conversations (a main chat and, when chosen, its
workers), frozen when it was exported. This reader checks every hash, then lets an agent look
through the capture the way Codex's own history tools look through a worker's history:

    list_windows     one row per frozen conversation snapshot (legacy name: window)
    list_items       items in order, filtered by agent, kind, role or failure
    read_item        one item, or one field of it, in a bounded character range
    search_contents  literal substring search over every recorded value
    cite             check citations returned by a reviewer and print the cited text
    handoff          a short conclusion and explicitly selected excerpts, each cited

Every result carries a citation, agent-trace://<window_id>/<item_id>?field=...&chars=a-b, that
Agent Trace can open on the sender's machine at the same captured value, even after the live
conversation has moved on. The reader never runs recorded commands and never reads anything but
the named capture.

Usage: python capture_reader.py [--capture PATH] <command> [options]   (add --help to any command)
PATH is the .trace.zip or its extracted folder; by default the folder holding this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
from pathlib import Path
from zipfile import BadZipFile, ZipFile

FORMAT = 'agent_trace_capture_v1'
MANIFEST_HASH_SCHEME = 'canonical_json_without_manifest_sha256_v1'
SNAPSHOT_SCHEMA = 'codex_native_v1'
MAX_LIMIT_CHARS = 48000
MAX_CONTENT_BYTES = 1024 * 1024 * 1024
ROLES = {'UserMessage': 'user', 'AgentMessage': 'assistant', 'Reasoning': 'assistant'}
KINDS = ('CommandExecution', 'FileChange', 'McpToolCall', 'AgentMessage', 'UserMessage', 'Reasoning',
         'SubAgentActivity', 'Extension', 'ContextCompaction')


class CaptureError(ValueError):
    pass


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot_digest(snapshot: dict) -> str:
    """The capture identity Agent Trace assigns: canonical JSON without the digest or local path."""
    content = {k: v for k, v in snapshot.items() if k != 'sha256'}
    content['source'] = {k: v for k, v in snapshot['source'].items() if k != 'path'}
    return sha(canonical(content).encode())


def value_digest(value) -> str:
    return sha((value if isinstance(value, str) else canonical(value)).encode())


def manifest_digest(manifest: dict) -> str:
    return sha(canonical({k: v for k, v in manifest.items() if k != 'manifest_sha256'}).encode())


# ---------------------------------------------------------------- loading and verification

class Capture:
    def __init__(self, manifest: dict, windows: dict[str, dict]):
        self.manifest = manifest
        self.windows = windows  # window_id -> snapshot
        self.by_session = {}
        for w in manifest['windows']:
            self.by_session.setdefault(w['session_id'], []).append(w['window_id'])

    @classmethod
    def open(cls, path: str | Path) -> 'Capture':
        path = Path(path)
        members = _read_members(path)
        if 'manifest.json' not in members:
            raise CaptureError('No manifest.json: this is not an Agent Trace capture.')
        manifest = json.loads(members['manifest.json'])
        if manifest.get('format') != FORMAT:
            raise CaptureError(f"Unsupported capture format {manifest.get('format')!r}.")
        if 'manifest_sha256' in manifest:
            if manifest.get('manifest_hash_scheme') != MANIFEST_HASH_SCHEME:
                raise CaptureError('Unsupported manifest hash scheme.')
            if manifest_digest(manifest) != manifest['manifest_sha256']:
                raise CaptureError('Manifest content does not match its checksum.')
        for name, spec in manifest.get('members', {}).items():
            data = members.get(name)
            if data is None:
                raise CaptureError(f'Capture member missing: {name}')
            if len(data) != spec['bytes'] or sha(data) != spec['sha256']:
                raise CaptureError(f'Capture member changed since export: {name}')
        windows = {}
        for w in manifest['windows']:
            if w['window_id'] in windows:
                raise CaptureError(f'Duplicate window: {w["window_id"]}')
            name = f"windows/{w['window_id']}.json"
            if name not in manifest.get('members', {}):
                raise CaptureError(f'Window {w["window_id"]} is listed but not hashed in the manifest.')
            snapshot = json.loads(members[name])
            if snapshot.get('schema') != SNAPSHOT_SCHEMA or snapshot.get('sha256') != w['window_id']:
                raise CaptureError(f'Window identity mismatch: {w["window_id"]}')
            if snapshot_digest(snapshot) != w['window_id']:
                raise CaptureError(f'Window content does not match its capture ID: {w["window_id"]}')
            if snapshot.get('session_id') != w['session_id']:
                raise CaptureError(f'Window session mismatch: {w["window_id"]}')
            ids = [entry['item_id'] for entry in snapshot['items']]
            if len(ids) != len(set(ids)):
                raise CaptureError(f'Duplicate item IDs in window {w["window_id"]}.')
            windows[w['window_id']] = snapshot
        expected = sha(canonical(sorted(windows)).encode())
        if manifest.get('capture_id') != expected:
            raise CaptureError('capture_id does not match the captured window set.')
        cap = cls(manifest, windows)
        if manifest['root_session_id'] not in cap.by_session:
            raise CaptureError('The capture root is not included.')
        conclusion = manifest.get('conclusion', {})
        if conclusion.get('cite'):
            result = cite(cap, [conclusion['cite']])['results'][0]
            if not result['resolved'] or result['text'] != conclusion.get('text'):
                raise CaptureError('Conclusion text is not the exact text at its citation.')
        return cap

    # -- addressing
    def window(self, window_id: str = '', agent_name: str = '') -> tuple[str, dict]:
        if window_id:
            matches = [w for w in self.windows if w == window_id or (len(window_id) >= 8 and w.startswith(window_id))]
            if len(matches) != 1:
                raise CaptureError(f'window_id {window_id!r} is {"ambiguous" if matches else "not in this capture"}; '
                                   'no other version is consulted.')
            return matches[0], self.windows[matches[0]]
        if agent_name:
            sessions = [s for s in self.by_session if s == agent_name or (len(agent_name) >= 6 and s.startswith(agent_name))]
            if not sessions:
                sessions = [w['session_id'] for w in self.manifest['windows'] if w.get('nickname') == agent_name]
            if len(set(sessions)) != 1:
                raise CaptureError(f'agent_name {agent_name!r} is {"ambiguous" if sessions else "not in this capture"}.')
            if len(self.by_session[sessions[0]]) != 1:
                raise CaptureError('More than one snapshot of this session is included; pass --window-id.')
            window_id = self.by_session[sessions[0]][0]
            return window_id, self.windows[window_id]
        root = self.manifest['root_session_id']
        if len(self.by_session[root]) != 1:
            raise CaptureError('More than one snapshot of the capture root is included; pass --window-id.')
        window_id = self.by_session[root][0]
        return window_id, self.windows[window_id]

    def entry(self, window_id: str, item_id: str) -> dict:
        for entry in self.windows[window_id]['items']:
            if entry['item_id'] == item_id:
                return entry
        raise CaptureError(f'item {item_id!r} is not in window {window_id}.')


def _read_members(path: Path) -> dict[str, bytes]:
    if path.is_dir():
        out, total = {}, 0
        for f in path.rglob('*'):
            if f.is_file() and '__pycache__' not in f.parts:
                total += f.stat().st_size
                if total > MAX_CONTENT_BYTES:
                    raise CaptureError('Capture is larger than this reader accepts.')
                out[f.relative_to(path).as_posix()] = f.read_bytes()
        return out
    try:
        with ZipFile(path) as z:
            names = z.namelist()
            if len(names) != len(set(names)):
                raise CaptureError('Duplicate members in capture ZIP.')
            if sum(i.file_size for i in z.infolist()) > MAX_CONTENT_BYTES:
                raise CaptureError('Capture is larger than this reader accepts.')
            prefix = _common_prefix(names)
            return {n[len(prefix):]: z.read(n) for n in names if not n.endswith('/')}
    except BadZipFile as exc:
        raise CaptureError(f'Not a ZIP file: {exc}') from None


def _common_prefix(names: list[str]) -> str:
    """Accept a ZIP whose members sit under one top folder (as Finder and some uploads produce)."""
    if 'manifest.json' in names:
        return ''
    tops = {n.split('/', 1)[0] for n in names if '/' in n}
    if len(tops) == 1 and all('/' in n for n in names):
        top = next(iter(tops)) + '/'
        if top + 'manifest.json' in names:
            return top
    return ''


def default_capture() -> Path:
    here = Path(__file__).resolve().parent
    if (here / 'manifest.json').is_file():
        return here
    zips = sorted(Path.cwd().glob('*.trace.zip'))
    if len(zips) == 1:
        return zips[0]
    raise CaptureError('Pass --capture PATH (the .trace.zip or its extracted folder).')


# ---------------------------------------------------------------- citations

def make_cite(window_id: str, item_id: str, field: str = '', start: int | None = None, end: int | None = None) -> str:
    query = {}
    if field:
        query['field'] = field
    if start is not None and end is not None:
        query['chars'] = f'{start}-{end}'
    q = urllib.parse.urlencode(query, safe='/')
    return f"agent-trace://{window_id}/{urllib.parse.quote(item_id, safe='')}" + (f'?{q}' if q else '')


def parse_cite(cite: str) -> dict:
    try:
        parsed = urllib.parse.urlsplit(cite.strip().strip('<>`'))
    except ValueError as exc:
        raise CaptureError(f'Bad citation URL: {exc}') from None
    if parsed.scheme != 'agent-trace' or not parsed.netloc:
        raise CaptureError(f'Not an agent-trace citation: {cite!r}')
    if parsed.fragment:
        raise CaptureError('Citation fragments are not supported.')
    item_id = urllib.parse.unquote(parsed.path.lstrip('/'))
    try:
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise CaptureError(f'Bad citation query: {exc}') from None
    query = {}
    for key, value in pairs:
        if key.startswith('amp;'):
            raise CaptureError('HTML-escaped citation query; use the exact URI with & between parameters, not &amp;.')
        if key not in ('field', 'chars'):
            raise CaptureError(f'Unknown citation parameter: {key!r}')
        if key in query:
            raise CaptureError(f'Duplicate citation parameter: {key!r}')
        query[key] = value
    out = {'window_id': parsed.netloc, 'item_id': item_id, 'field': query.get('field', '')}
    if 'chars' in query:
        a, _, b = query['chars'].partition('-')
        if not (a.isascii() and a.isdigit() and b.isascii() and b.isdigit()):
            raise CaptureError(f'Bad chars range in {cite!r}')
        try:
            start, end = int(a), int(b)
        except ValueError:
            raise CaptureError(f'Bad chars range in {cite!r}') from None
        if end < start:
            raise CaptureError(f'Bad chars range in {cite!r}')
        out['start'], out['end'] = start, end
    return out


# ---------------------------------------------------------------- values

def resolve_field(entry: dict, field: str):
    if not field:
        return entry
    if not field.startswith('/'):
        raise CaptureError('field must be a JSON Pointer such as /aggregated_output.')
    value = entry['item']
    for segment in field[1:].split('/'):
        if any(c == '~' and (i + 1 >= len(segment) or segment[i + 1] not in '01')
               for i, c in enumerate(segment)):
            raise CaptureError('Invalid JSON Pointer escape.')
        key = segment.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isascii() and key.isdigit() and str(int(key)) == key and int(key) < len(value):
            value = value[int(key)]
        else:
            raise CaptureError(f'field {field!r} does not exist in item {entry["item_id"]}.')
    return value


def failed(entry: dict) -> bool:
    item = entry['item']
    if type(item.get('exit_code')) is int and item['exit_code'] != 0:
        return True
    if str(item.get('status', '')).casefold() in ('failed', 'error', 'declined', 'cancelled', 'canceled'):
        return True
    result = item.get('result')
    return bool(item.get('error') or (isinstance(result, dict) and (result.get('isError') or result.get('is_error'))))


def preview(entry: dict) -> str:
    item = entry['item']
    kind = entry['kind']
    if kind == 'CommandExecution':
        value = item.get('command')
        if isinstance(value, list):
            value = value[-1] if len(value) == 3 and value[1] in ('-lc', '-c') else ' '.join(map(str, value))
    elif kind == 'McpToolCall':
        value = f"{item.get('server', '')}.{item.get('tool', '')}"
    elif kind in ('AgentMessage', 'UserMessage'):
        value = item.get('text') or item.get('message')
        if not value and isinstance(item.get('content'), list):
            value = '\n'.join(part['text'] for part in item['content']
                              if isinstance(part, dict) and isinstance(part.get('text'), str))
        value = value or item.get('content')
    elif kind == 'Reasoning':
        value = item.get('summary_text')
    elif kind == 'FileChange':
        value = [c.get('path') for c in item.get('changes', []) if isinstance(c, dict)] or item.get('changes')
    else:
        value = item.get('content', item)
    return value if isinstance(value, str) else canonical(value)


def leaves(value, pointer=''):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, pointer + '/' + k.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaves(v, f'{pointer}/{i}')


def row(window_id: str, entry: dict, max_chars: int) -> dict:
    item = entry['item']
    out = {'item_id': entry['item_id'], 'kind': entry['kind'], 'role': ROLES.get(entry['kind'], 'tool'),
           'status': entry.get('status'), 'failed': failed(entry), 'turn_id': entry.get('turn_id'),
           'completed_at_ms': entry.get('completed_at_ms'), 'truncated_content': preview(entry)[:max_chars],
           'cite': make_cite(window_id, entry['item_id'])}
    if 'exit_code' in item:
        out['exit_code'] = item['exit_code']
    if isinstance(item.get('aggregated_output'), str):
        out['output_chars'] = len(item['aggregated_output'])
    return out


# ---------------------------------------------------------------- commands (named like Codex's history tools)

def list_windows(cap: Capture) -> dict:
    rows = []
    for w in cap.manifest['windows']:
        snap = cap.windows[w['window_id']]
        rows.append({**{k: w.get(k) for k in ('window_id', 'session_id', 'nickname', 'parent_session_id', 'role')},
                     'agent_name': w['session_id'], 'item_count': len(snap['items']),
                     'failed_count': sum(failed(e) for e in snap['items'])})
    return {'capture': cap.manifest['capture_id'], 'root_session_id': cap.manifest['root_session_id'],
            'exported_at': cap.manifest['exported_at'], 'windows': rows,
            'unavailable': cap.manifest.get('unavailable_children', []), 'scope': cap.manifest.get('scope', {}),
            'conclusion': cap.manifest.get('conclusion'),
            'window_meaning': 'frozen conversation snapshot, not a model context window',
            'failed_meaning': 'recorded nonzero exit/status/error; not a count of failed tests'}


def list_items(cap: Capture, agent_name='', window_id='', kind='', role='', failed_only=False,
               limit=50, offset=0, recent_first=False, max_chars_per_item=300) -> dict:
    if limit < 1 or offset < 0 or max_chars_per_item < 0:
        raise CaptureError('limit must be positive; offset and max_chars_per_item must be nonnegative.')
    wid, snap = cap.window(window_id, agent_name)
    entries = [e for e in snap['items']
               if (not kind or e['kind'] == kind) and (not role or ROLES.get(e['kind'], 'tool') == role)
               and (not failed_only or failed(e))]
    if recent_first:
        entries = entries[::-1]
    page = entries[offset: offset + limit]
    return {'window_id': wid, 'session_id': snap['session_id'], 'total': len(entries), 'offset': offset,
            'next_offset': offset + limit if offset + limit < len(entries) else None,
            'items': [row(wid, e, max_chars_per_item) for e in page]}


def read_item(cap: Capture, item_id: str, window_id='', agent_name='', field='', offset_chars=0,
              limit_chars=12000) -> dict:
    if not 1 <= limit_chars <= MAX_LIMIT_CHARS or offset_chars < 0:
        raise CaptureError(f'limit_chars must be 1 to {MAX_LIMIT_CHARS}; offset_chars must be 0 or more.')
    wid, _ = cap.window(window_id, agent_name)
    entry = cap.entry(wid, item_id)
    value = resolve_field(entry, field)
    text = value if isinstance(value, str) else canonical(value)
    if offset_chars > len(text):
        raise CaptureError('offset_chars is beyond the end of this value.')
    end = min(len(text), offset_chars + limit_chars)
    return {'window_id': wid, 'session_id': entry['session_id'], 'item_id': item_id, 'kind': entry['kind'],
            'field': field, 'representation': 'text' if isinstance(value, str) else 'canonical_json',
            'offset_chars': offset_chars, 'end_chars': end, 'total_chars': len(text),
            'next_offset_chars': end if end < len(text) else None,
            'value_sha256': value_digest(value), 'range_sha256': sha(text[offset_chars:end].encode()),
            'content': text[offset_chars:end],
            'cite': make_cite(wid, item_id, field, offset_chars, end)}


def _match_span(text: str, query: str, ignore_case: bool):
    if not ignore_case:
        at = text.find(query)
        return (at, at + len(query)) if at >= 0 else None
    # Case folding can expand characters (ß -> ss). Map the match back to the
    # original decoded string before creating a citation.
    folded = text.casefold()
    at = folded.find(query.casefold())
    if at < 0:
        return None
    stop = at + len(query.casefold())
    start, end, offset = None, None, 0
    for i, char in enumerate(text):
        next_offset = offset + len(char.casefold())
        if start is None and next_offset > at:
            start = i
        if next_offset >= stop:
            end = i + 1
            break
        offset = next_offset
    return start, end


def search_contents(cap: Capture, query: str, agent_name='', window_id='', kind='', failed_only=False,
                    ignore_case=False, limit=20, recent_first=False, context_chars=160, all_windows=False) -> dict:
    if not query:
        raise CaptureError('query must not be empty.')
    if limit < 1 or context_chars < 0:
        raise CaptureError('limit must be positive; context_chars must be nonnegative.')
    targets = list(cap.windows.items()) if all_windows else [cap.window(window_id, agent_name)]
    hits = []
    for wid, snap in targets:
        entries = snap['items'][::-1] if recent_first else snap['items']
        for e in entries:
            if (kind and e['kind'] != kind) or (failed_only and not failed(e)):
                continue
            for pointer, text in leaves(e['item']):
                span = _match_span(text, query, ignore_case)
                if span is None:
                    continue
                at, end = span
                a, b = max(0, at - context_chars), min(len(text), end + context_chars)
                hits.append({'window_id': wid, 'session_id': snap['session_id'], 'item_id': e['item_id'],
                             'kind': e['kind'], 'failed': failed(e), 'field': pointer, 'match_chars': [at, end],
                             'passage': text[a:b], 'passage_chars': [a, b],
                             'cite': make_cite(wid, e['item_id'], pointer, at, end),
                             'passage_cite': make_cite(wid, e['item_id'], pointer, a, b)})
                break
            if len(hits) > limit:
                break
        if len(hits) > limit:
            break
    return {'query': query, 'case_sensitive': not ignore_case, 'searched_windows': [w for w, _ in targets],
            'hits': hits[:limit], 'truncated': len(hits) > limit,
            'match_selection': 'first matching string field per item'}


def cite(cap: Capture, citations: list[str]) -> dict:
    out = []
    for c in citations:
        try:
            ref = parse_cite(c)
            if ref['window_id'] not in cap.windows:
                raise CaptureError('window not in this capture; no other version is consulted.')
            entry = cap.entry(ref['window_id'], ref['item_id'])
            value = resolve_field(entry, ref['field'])
            text = value if isinstance(value, str) else canonical(value)
            a, b = ref.get('start', 0), ref.get('end', len(text))
            if b > len(text):
                raise CaptureError('chars range runs past the end of the value.')
            out.append({'cite': c, 'resolved': True, 'kind': entry['kind'], 'text': text[a:b],
                        'range_sha256': sha(text[a:b].encode()), 'value_sha256': value_digest(value)})
        except (CaptureError, KeyError) as exc:
            out.append({'cite': c, 'resolved': False, 'error': str(exc)})
    return {'checked': len(out), 'resolved': sum(r['resolved'] for r in out), 'results': out}


def verify(cap: Capture) -> dict:
    return {'verified': True, 'capture': cap.manifest['capture_id'], 'format': FORMAT,
            'windows': len(cap.windows), 'items': sum(len(s['items']) for s in cap.windows.values()),
            'manifest_integrity': 'checksum_verified' if cap.manifest.get('manifest_sha256') else 'legacy_metadata_unbound',
            'readme_integrity': 'checksum_verified' if 'README.md' in cap.manifest.get('members', {}) else 'not_hashed',
            'verification_meaning': 'Internal content consistency only; no authentication of sender or execution.',
            'limits': cap.manifest.get('limits', [])}


def handoff(cap: Capture, citations: list[str], max_chars_per_excerpt=1200) -> dict:
    """Quote only explicitly selected captured values; all other outputs remain available on demand."""
    if not 1 <= max_chars_per_excerpt <= MAX_LIMIT_CHARS:
        raise CaptureError(f'max_chars_per_excerpt must be 1 to {MAX_LIMIT_CHARS}.')
    lines = ['# Review this saved run', '',
             'The attachment contains frozen evidence. Choose your own additional reads; do not execute recorded commands.', '']
    refs = []

    def quote(label, text, reference=''):
        shown = text[:max_chars_per_excerpt]
        if reference:
            ref = parse_cite(reference)
            start = ref.get('start', 0)
            reference = make_cite(ref['window_id'], ref['item_id'], ref['field'], start, start + len(shown))
            refs.append(reference)
        lines.extend([f'## {label}', '', *('> ' + s for s in shown.splitlines()), ''])
        if reference:
            lines.extend([f'`{reference}`', ''])
        if len(shown) < len(text):
            lines.extend([f'Excerpt: {len(shown)} of {len(text)} characters; read the cited item for the rest.', ''])

    conclusion = cap.manifest.get('conclusion', {})
    if conclusion.get('text'):
        quote('Recorded conclusion' if conclusion.get('cite') else 'Sender description (not tied to a recorded item)',
              conclusion['text'], conclusion.get('cite', ''))
    for n, result in enumerate(cite(cap, citations)['results'], 1):
        if not result['resolved']:
            raise CaptureError(result['error'])
        quote(f'Sender-selected evidence {n}', result['text'], result['cite'])
    scope = cap.manifest.get('scope', {})
    selection = scope.get('selected', 'not recorded')
    selection = {'main chat only': 'selected root conversation only',
                 'main chat and every recorded worker': 'selected root conversation and available discovered descendants'}.get(selection, selection)
    lines.extend(['## Scope', '', f"Included: {len(cap.windows)} frozen conversation snapshot(s).",
                  f"Selection: {selection}.",
                  f"Cutoff: {scope.get('cutoff', 'not recorded')}."])
    if scope.get('note'):
        lines.append(scope['note'])
    if not cap.manifest.get('include_children'):
        lines.append('Descendant discovery was not requested; this does not establish that no other workers existed.')
    for omitted in cap.manifest.get('unavailable_children', []):
        lines.append(f"Unavailable: {omitted['session_id']} ({omitted.get('reason', 'not recorded')}).")
    lines.extend(['', '## Continue reading', '', '```sh',
                  'python capture_reader.py list_windows',
                  'python capture_reader.py list_items --kind CommandExecution',
                  'python capture_reader.py search_contents --query "your question" --all-windows',
                  'python capture_reader.py read_item --window-id <snapshot> --item-id <item> --field /aggregated_output',
                  '```', '',
                  'Return the exact citations for the evidence you used. Saved outputs do not establish current code state or model input.'])
    return {'markdown': '\n'.join(lines) + '\n', 'citations': refs}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--capture', help='The .trace.zip or its extracted folder.')
    p.add_argument('--text', action='store_true', help='Print content fields as plain text instead of JSON.')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('verify', help='Check every hash in the capture.')
    sub.add_parser('list_windows', help='One row per captured conversation.')
    li = sub.add_parser('list_items', help='Items in order, filtered.')
    ri = sub.add_parser('read_item', help='Read one item or field in a character range.')
    sc = sub.add_parser('search_contents', help='Literal substring search.')
    ci = sub.add_parser('cite', help='Check citations and print the cited text.')
    ho = sub.add_parser('handoff', help='Quote the conclusion and explicitly chosen evidence as a short first copy.')
    ho.add_argument('--cite', dest='citations', action='append', default=[], help='An exact evidence citation; repeat as needed.')
    ho.add_argument('--max-chars-per-excerpt', type=int, default=1200)
    for s in (li, ri, sc):
        s.add_argument('--agent-name', default='', help='Session ID (or unique prefix, or nickname). Default: the main chat.')
        s.add_argument('--window-id', default='', help='Frozen conversation snapshot ID from list_windows (or unique 8+ character prefix).')
    for s in (li, sc):
        s.add_argument('--kind', default='', choices=('',) + KINDS)
        s.add_argument('--failed-only', action='store_true')
        s.add_argument('--recent-first', action='store_true')
        s.add_argument('--limit', type=int, default=50 if s is li else 20)
    li.add_argument('--role', default='', choices=('', 'user', 'assistant', 'tool'))
    li.add_argument('--offset', type=int, default=0)
    li.add_argument('--max-chars-per-item', type=int, default=300)
    ri.add_argument('--item-id', required=True)
    ri.add_argument('--field', default='', help='JSON Pointer, for example /aggregated_output. Empty: whole item.')
    ri.add_argument('--offset-chars', type=int, default=0)
    ri.add_argument('--limit-chars', type=int, default=12000)
    sc.add_argument('--query', required=True, help='Case-sensitive literal substring.')
    sc.add_argument('--ignore-case', action='store_true')
    sc.add_argument('--all-windows', action='store_true', help='Search every captured conversation.')
    ci.add_argument('citations', nargs='+')
    a = p.parse_args(argv)
    try:
        cap = Capture.open(a.capture or default_capture())
        if a.command == 'verify':
            out = verify(cap)
        elif a.command == 'list_windows':
            out = list_windows(cap)
        elif a.command == 'list_items':
            out = list_items(cap, a.agent_name, a.window_id, a.kind, a.role, a.failed_only, a.limit, a.offset,
                             a.recent_first, a.max_chars_per_item)
        elif a.command == 'read_item':
            out = read_item(cap, a.item_id, a.window_id, a.agent_name, a.field, a.offset_chars, a.limit_chars)
        elif a.command == 'search_contents':
            out = search_contents(cap, a.query, a.agent_name, a.window_id, a.kind, a.failed_only, a.ignore_case,
                                  a.limit, a.recent_first, all_windows=a.all_windows)
        elif a.command == 'handoff':
            out = handoff(cap, a.citations, a.max_chars_per_excerpt)
        else:
            out = cite(cap, a.citations)
    except (CaptureError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2
    if a.text and a.command == 'read_item':
        print(out['content'])
        print(f"\n[{out['cite']} · chars {out['offset_chars']}-{out['end_chars']} of {out['total_chars']}"
              f" · value sha256 {out['value_sha256']}]")
    elif a.text and a.command == 'handoff':
        print(out['markdown'], end='')
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
