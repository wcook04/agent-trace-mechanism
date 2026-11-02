"""Portable views of parsed records; the native app has additional formatting."""
import json


def structured(turns):
    return [{'prompt': turn.prompt_text, 'assistant': turn.assistant_text,
             'complete': turn.is_complete, 'turn_ended': turn.turn_ended,
             'tool_evidence_complete': turn.tool_evidence_complete, 'partial_reason': turn.partial_reason,
             'tools': [{'name': e.name, 'call_id': e.tool_call_id, 'input': e.input,
                        'output': e.output_text, 'error': e.is_error,
                        'call_observed': e.call_observed, 'result_observed': e.result_observed,
                        'missing_call': not e.call_observed, 'missing_result': not e.result_observed} for e in turn.tool_events]}
            for turn in turns]


def chronological_events(turn):
    """Order distinct records; do not claim ordering within one provider record."""
    events = []
    for event in turn.assistant_events:
        events.append((event.source_record_index, 'assistant', event))
    for event in turn.tool_events:
        indices = event.source_record_indices
        if event.call_observed:
            events.append((indices[0] if indices else float('inf'), 'call', event))
        if event.result_observed:
            events.append((indices[-1] if indices else float('inf'), 'result', event))
    return sorted(events, key=lambda item: item[0])


def render(turns, detail=False):
    lines = []
    for turn in turns:
        lines.extend([f'USER: {json.dumps(turn.prompt_text, ensure_ascii=False)}',
                      f'STATUS: {"complete" if turn.is_complete else "incomplete"}'])
        if not detail:
            lines.append('TOOL_RESULTS: [omitted in compact view]')
        for _, kind, event in chronological_events(turn):
            if kind == 'assistant':
                lines.append(f'ASSISTANT: {json.dumps(event.text, ensure_ascii=False)}')
            elif kind == 'call':
                allowed = {'path', 'file_path', 'filename', 'command', 'cmd'}
                displayed = event.input if detail else {k: v for k, v in event.input.items() if k in allowed}
                lines.append(f'TOOL {event.name} ({event.tool_call_id or "unidentified"}): {json.dumps(displayed, ensure_ascii=False, sort_keys=True)}')
            elif detail:
                lines.append(f'RESULT {event.name} ({event.tool_call_id or "unidentified"}): {json.dumps(event.output_text, ensure_ascii=False)}')
        if not turn.assistant_events and turn.assistant_text:
            lines.append(f'ASSISTANT: {json.dumps(turn.assistant_text, ensure_ascii=False)}')
        if turn.partial_reason:
            lines.append(f'PARTIAL: {turn.partial_reason}')
    return '\n'.join(lines)
