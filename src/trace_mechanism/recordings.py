"""Local identity and version checks shared by the workbench and registration."""
from contextlib import contextmanager
import hashlib
from pathlib import Path

from .codex_native import MAX_SOURCE_BYTES


def recording_id(path, provider, session_id):
    st = path.stat()
    # A rename preserves the file. An independent copy is separately selectable.
    origin = (st.st_dev, st.st_ino, getattr(st, 'st_birthtime', None)) if st.st_ino else str(path.resolve())
    return hashlib.sha256(repr((provider, session_id, origin)).encode()).hexdigest()


def claude_worker(path, session_id):
    directory = next((p for p in path.parents if p.name == 'subagents' and p.parent.name == session_id), None)
    if directory:
        owner = directory.parent
        return owner.parent / (session_id + '.jsonl'), session_id + '/' + path.relative_to(directory).with_suffix('').as_posix()
    return None, session_id


def file_version(path):
    st = Path(path).stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


@contextmanager
def fixed_selection(paths):
    paths = list(paths)
    versions = {p: file_version(p) for p in paths}
    if len(paths) > 64 or sum(v[2] for v in versions.values()) > MAX_SOURCE_BYTES:
        raise ValueError('Choose at most 64 recordings and 256 MiB of source data.')
    yield versions
    if any(file_version(p) != v for p, v in versions.items()):
        raise ValueError('A selected source changed during capture. Refresh and try again.')
