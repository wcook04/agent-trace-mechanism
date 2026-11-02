#!/usr/bin/env python3
"""Explicit-file selection for the fictional repair-cafe recording, not a general redactor."""
import argparse
import hashlib
import json
from pathlib import Path


def select(source, destination, workspace_prefix, coordinator_id):
    raw = source.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    replacements = {workspace_prefix: '<example-workspace>', coordinator_id: 'controlled-coordinator'}
    selected, kept, before = [], [], None
    for number, row in enumerate(rows, 1):
        payload = row.get('payload', {})
        kind, subtype = row.get('type'), payload.get('type')
        keep = (kind == 'event_msg' and subtype in ('task_started', 'task_complete')) or (
            kind == 'response_item' and (
                subtype in ('function_call', 'function_call_output', 'custom_tool_call', 'custom_tool_call_output') or
                (subtype == 'message' and payload.get('role') == 'assistant' and payload.get('channel') != 'analysis')))
        if not keep:
            continue
        text = json.dumps(row, ensure_ascii=False)
        for old, new in replacements.items():
            text = text.replace(old, new)
        selected.append(text + '\n')
        kept.append(number)
        if subtype == 'task_complete' and before is None:
            before = ''.join(selected)
    if before is None:
        raise ValueError('No first completed turn found')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'source-before.jsonl').write_text(before, encoding='utf-8')
    (destination / 'source-after.jsonl').write_text(''.join(selected), encoding='utf-8')
    receipt = {
        'source_session_id': '01a19dee-f8b7-7b02-9f5c-ac8a2431350d',
        'original_sha256': hashlib.sha256(raw).hexdigest(),
        'original_records': len(rows), 'retained_original_lines_1_based': kept,
        'selection': 'Lifecycle, visible assistant messages, tool calls and results only. Actual delivered requests remain inside their recorded codex_delegation input elements.',
        'omitted': 'Injected instructions/environment, reasoning, telemetry and all unselected record types. No session metadata or synthetic user-message events added.',
        'replacements': {'workspace_prefix': '<example-workspace>', 'coordinator_thread_id': 'controlled-coordinator'},
        'before_rule': 'Selected prefix through the first task_complete record.',
        'original_session_complete': False,
    }
    (destination / 'selection.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('source', type=Path)
    cli.add_argument('destination', type=Path)
    cli.add_argument('--workspace-prefix', required=True)
    cli.add_argument('--coordinator-id', required=True)
    args = cli.parse_args()
    select(args.source, args.destination, args.workspace_prefix, args.coordinator_id)
