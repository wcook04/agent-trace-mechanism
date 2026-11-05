"""Bundled Markdown starters with persistent user overrides."""

import hashlib
import os
from pathlib import Path
import re
import tempfile

BUNDLED = Path(__file__).with_name("prompts")
SLUG = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}")
LIMIT = 1024 * 1024


def user_dir():
    return (
        Path(
            os.environ.get("AGENT_TRACE_PROMPTS")
            or Path.home() / ".agent-trace/prompts"
        )
        .expanduser()
        .absolute()
    )


def read(slug):
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ValueError("Use a name with letters, numbers, dashes or underscores.")
    for folder in (user_dir(), BUNDLED):
        path = folder / (slug + ".md")
        if path.is_symlink():
            raise ValueError("Linked prompt files are not supported.")
        if path.is_file():
            if path.stat().st_size > LIMIT:
                raise ValueError("Prompt exceeds 1 MiB.")
            raw = path.read_text(encoding="utf-8")
            head, sep, body = (
                raw[4:].partition("\n---\n")
                if raw.startswith("---\n")
                else ("", "", raw)
            )
            body = body.lstrip("\n") if sep else raw
            fields = (
                dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
                if sep
                else {}
            )
            title = fields.get("title", "").strip() or next(
                (s.lstrip("# ").strip()[:80] for s in body.splitlines() if s.strip()),
                slug,
            )
            return dict(
                slug=slug,
                title=title,
                body=body,
                raw=raw,
                user=folder != BUNDLED,
                label=fields.get("cockpit_slot", "").strip() or slug,
                char_count=len(body),
                byte_count=len(body.encode()),
                sha16=hashlib.sha256(body.encode()).hexdigest()[:16],
                revision=hashlib.sha256(raw.encode()).hexdigest(),
            )
    return None


def listing():
    names = {
        p.stem
        for folder in (BUNDLED, user_dir())
        for p in folder.glob("*.md")
        if SLUG.fullmatch(p.stem)
    }
    out = []
    for name in sorted(names):
        try:
            item = read(name)
        except (OSError, ValueError):
            continue
        if item:
            out.append(
                {
                    k: item[k]
                    for k in ("slug", "title", "user", "label", "char_count", "sha16")
                }
            )
    return out


def save(slug, raw, revision):
    current = read(slug)
    if (current or {}).get("revision") != revision:
        raise ValueError(
            "This prompt already exists or changed. Reopen it before saving."
        )
    if not isinstance(raw, str) or not raw.strip() or len(raw.encode()) > LIMIT:
        raise ValueError("Enter a nonempty prompt of at most 1 MiB.")
    directory = user_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / (slug + ".md")
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temp:
        temp.write(raw.encode())
    try:
        if current:
            os.replace(temp.name, target)
        else:
            os.link(temp.name, target)
    finally:
        Path(temp.name).unlink(missing_ok=True)
    return read(slug)
