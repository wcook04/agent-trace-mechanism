"""Small, intentionally non-equivalent projections of the production trace views."""
import json


def structured(turns):
    return [{'prompt': turn.prompt_text, 'assistant': turn.assistant_text,
             'complete': turn.is_complete, 'partial_reason': turn.partial_reason,
             'tools': [{'name': e.name, 'call_id': e.tool_call_id, 'input': e.input,
                        'output': e.output_text, 'error': e.is_error,
                        'missing_result': len(e.source_record_indices) < 2} for e in turn.tool_events]}
            for turn in turns]


def render(turns, detail=False):
    lines = []
    for turn in turns:
        lines.extend([f'USER: {turn.prompt_text}', f'STATUS: {"complete" if turn.is_complete else "incomplete"}'])
        for event in turn.tool_events:
            allowed = {'path', 'file_path', 'filename', 'command', 'cmd'}
            displayed = event.input if detail else {k: v for k, v in event.input.items() if k in allowed}
            lines.append(f'TOOL {event.name} ({event.tool_call_id}): {json.dumps(displayed, ensure_ascii=False, sort_keys=True)}')
            lines.append(f'RESULT: {event.output_text}' if detail else 'RESULT: [omitted in compact view]')
        if turn.assistant_text:
            lines.append(f'ASSISTANT: {turn.assistant_text}')
        if turn.partial_reason:
            lines.append(f'PARTIAL: {turn.partial_reason}')
    return '\n'.join(lines)
