"""Adapted in-memory tool boundary: explicit registry, no MCP transport or home scan."""
import hashlib
from .parser import parse_claude_session, parse_codex_session
from .views import render


class AgentTools:
    def __init__(self, entries):
        # Caller supplies provider, session_id, title and path; no discovery.
        self.entries = list(entries)
        self.snapshots = {}

    def search_trace_threads(self, query):
        terms = query.casefold().split()
        return [{key: row[key] for key in ('provider', 'session_id', 'title')}
                for row in self.entries if all(term in
                f"{row['provider']} {row['session_id']} {row['title']}".casefold() for term in terms)]

    def read_chat_context(self, provider, session_id, scope='full_thread_concise', limit=24000):
        rows = [r for r in self.entries if (r['provider'], r['session_id']) == (provider, session_id)]
        if len(rows) != 1 or provider not in ('codex', 'claude'):
            raise ValueError('Choose one registered provider and session ID.')
        if scope not in ('full_thread_concise', 'full_thread'):
            raise ValueError('This demo supports compact and detailed full-thread scopes only.')
        parser = parse_codex_session if provider == 'codex' else parse_claude_session
        text = render(parser(rows[0]['path']), detail=scope == 'full_thread')
        digest = hashlib.sha256(text.encode()).hexdigest()
        self.snapshots[digest] = text
        return {'provider': provider, 'session_id': session_id, 'scope': scope,
                **self.read_trace_page(digest, 0, limit)}

    def read_trace_page(self, sha256, offset=0, limit=24000):
        if sha256 not in self.snapshots or offset < 0 or limit < 1:
            raise ValueError('Unknown snapshot or invalid page.')
        text = self.snapshots[sha256]
        if offset > len(text):
            raise ValueError('Offset is beyond the snapshot.')
        end = min(offset + limit, len(text))
        return {'sha256': sha256, 'text': text[offset:end],
                'next_offset': end if end < len(text) else None, 'total_chars': len(text)}
