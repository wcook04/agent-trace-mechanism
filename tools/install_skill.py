#!/usr/bin/env python3
"""Copy the portable Agent Trace skill; never change MCP configuration or register chats."""
import argparse
import os
from pathlib import Path
import shutil

SOURCE = Path(__file__).resolve().parents[1] / 'skills/agent-trace'


def destination(host, scope, project=None, skills_dir=None):
    if skills_dir is not None:
        if project is not None:
            raise ValueError('Choose --skills-dir or --project, not both.')
        return skills_dir.expanduser().absolute() / 'agent-trace'
    if scope == 'project':
        if project is None or not project.expanduser().is_dir():
            raise ValueError('Project scope requires --project pointing to an existing project directory.')
        root = project.expanduser().absolute()
    else:
        if project is not None:
            raise ValueError('--project requires --scope project.')
        root = Path.home()
    if host == 'claude':
        config = Path(os.environ.get('CLAUDE_CONFIG_DIR') or root / '.claude') if scope == 'user' else root / '.claude'
        return config.expanduser().absolute() / 'skills/agent-trace'
    return root / '.agents/skills/agent-trace'


def install(target, source=SOURCE):
    files = [p for p in source.rglob('*') if p.is_file()]
    if not (source / 'SKILL.md').is_file() or any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('Skill source must contain SKILL.md and regular files, without symlinks.')
    if target.exists() or target.is_symlink():
        raise FileExistsError(f'Skill already exists: {target}. Review or move it before installing; nothing was replaced.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()  # Refuse a destination created concurrently, including a symlink.
    try:
        for path in files:
            out = target / path.relative_to(source)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, out)
    except Exception:
        shutil.rmtree(target)  # Only the new directory created by this invocation.
        raise
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, choices=('codex', 'claude'))
    parser.add_argument('--scope', choices=('user', 'project'), default='user')
    parser.add_argument('--project', type=Path, help='Target project, not the Agent Trace checkout')
    parser.add_argument('--skills-dir', type=Path, help='Custom host skill directory; agent-trace is created inside it')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        target = destination(args.host, args.scope, args.project, args.skills_dir)
        if not args.dry_run:
            install(target)
        print(('Would install: ' if args.dry_run else 'Installed: ') + str(target))
        print('Skill instructions only. No chats were registered and no MCP configuration changed.')
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Agent Trace skill: {exc}\n')


if __name__ == '__main__':
    main()
