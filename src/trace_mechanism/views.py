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


def chronological_events(turn, thinking=False):
    """Order distinct records; do not claim ordering within one provider record."""
    events = []
    if thinking:
        for event in getattr(turn, 'thinking_events', ()):
            events.append((event.source_record_index, 'thinking', event))
    for event in turn.assistant_events:
        events.append((event.source_record_index, 'assistant', event))
    for event in turn.tool_events:
        indices = event.source_record_indices
        if event.call_observed:
            events.append((indices[0] if indices else float('inf'), 'call', event))
        if event.result_observed:
            events.append((indices[-1] if indices else float('inf'), 'result', event))
    return sorted(events, key=lambda item: item[0])


COMPACT_INPUT_KEYS = {'path', 'file_path', 'filename', 'command', 'cmd'}
REPORT_TOOL = 'SubagentHandback'


def _left_out(size, error=False):
    return (f"[left out of the compact view: {size:,} character{'' if size == 1 else 's'}"
            f"{', marked as an error' if error else ''}]")


def _size(value):
    return len(value) if isinstance(value, str) else len(json.dumps(value, ensure_ascii=False))


def compact_input(value):
    """Keep paths and commands; name every other input and give its length."""
    if not isinstance(value, dict):
        return _left_out(_size(value))
    return {key: item if key in COMPACT_INPUT_KEYS else _left_out(_size(item)) for key, item in value.items()}


def delivered_report(turn):
    """The call id of a subagent's final report, when that report ended the turn.

    Claude Code ends a subagent's run at a successful SubagentHandback call, so
    no assistant message follows it and the parser reports the turn as partial.
    """
    events = chronological_events(turn)
    if not events:
        return None
    _, kind, event = events[-1]
    if kind == 'result' and event.name == REPORT_TOOL and not event.is_error \
            and all(e.call_observed and e.result_observed for e in turn.tool_events):
        return event.tool_call_id or 'unidentified'
    return None


def render(turns, detail=False, thinking=False):
    lines = []
    for turn in turns:
        report = delivered_report(turn)
        lines.extend([f'USER: {json.dumps(turn.prompt_text, ensure_ascii=False)}',
                      f'STATUS: {"complete" if turn.is_complete or report else "incomplete"}'])
        origin = getattr(turn, 'user_origin', '')
        if origin:
            lines.append(f'WRITTEN_BY: Claude Code, not the user ({origin})')
        for _, kind, event in chronological_events(turn, thinking):
            call = f'{event.name} ({event.tool_call_id or "unidentified"})' if kind in ('call', 'result') else ''
            if kind == 'thinking':
                lines.append(f'THINKING: {json.dumps(event.text, ensure_ascii=False)}')
            elif kind == 'assistant':
                lines.append(f'ASSISTANT: {json.dumps(event.text, ensure_ascii=False)}')
            elif kind == 'call':
                displayed = event.input if detail else compact_input(event.input)
                lines.append(f'TOOL {call}: {json.dumps(displayed, ensure_ascii=False, sort_keys=True)}')
            elif detail:
                lines.append(f'RESULT {call}: {json.dumps(event.output_text, ensure_ascii=False)}')
            else:
                lines.append(f'RESULT {call}: {json.dumps(_left_out(_size(event.output_text or ""), event.is_error))}')
        if not turn.assistant_events and turn.assistant_text:
            lines.append(f'ASSISTANT: {json.dumps(turn.assistant_text, ensure_ascii=False)}')
        if report:
            lines.append(f'FINAL_REPORT: delivered to the caller by the {REPORT_TOOL} call {report}, which ended the run')
        elif turn.partial_reason:
            lines.append(f'PARTIAL: {turn.partial_reason}')
    return '\n'.join(lines)
