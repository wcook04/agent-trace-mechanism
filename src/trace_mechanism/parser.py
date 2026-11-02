"""Provider JSONL parsing functions extracted unchanged from Agent Trace."""
from __future__ import annotations
import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CLAUDE_COMPLETE_STOP_REASONS = {"end_turn", "max_tokens", "stop_sequence", "refusal"}
CODEX_EXIT_CODE_RE = re.compile(r"Process exited with code\s+(-?\d+)")

@dataclass
class ToolEvent:
    index: int
    name: str
    input: dict
    tool_call_id: str | None
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    is_error: bool
    output_text: str
    output_char_count: int
    output_sha256_16: str
    exit_code: int | None = None
    outcome_pending: bool = False
    source_record_indices: list[int] = field(default_factory=list)


@dataclass
class AssistantEvent:
    text: str
    source_record_index: int
    timestamp: str | None = None


@dataclass
class Turn:
    provider: str
    session_id: str
    session_file: str
    turn_id: str
    turn_index: int
    cwd: str | None
    started_at: str | None
    completed_at: str | None
    prompt_text: str
    prompt_char_count: int
    prompt_sha256_16: str
    tool_events: list[ToolEvent]
    assistant_text: str
    assistant_events: list[AssistantEvent] = field(default_factory=list)
    is_complete: bool = False
    partial_reason: str | None = None
    last_stop_reason: str | None = None
    source_record_indices: list[int] = field(default_factory=list)
    source_ref: dict = field(default_factory=dict)


def _sha16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _iso_diff_ms(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    try:
        t1 = _dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
        t2 = _dt.datetime.fromisoformat(b.replace("Z", "+00:00"))
        return int((t2 - t1).total_seconds() * 1000)
    except Exception:
        return None


def _flatten_claude_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for c in content:
        if not isinstance(c, dict):
            continue
        ct = c.get("type")
        if ct == "text":
            parts.append(c.get("text", ""))
        elif ct == "image":
            parts.append("[image attachment]")
        elif ct == "tool_use":
            parts.append(f"[tool_use {c.get('name')!r}]")
        elif ct == "tool_result":
            inner = c.get("content")
            if isinstance(inner, str):
                parts.append(inner)
            elif isinstance(inner, list):
                for b in inner:
                    if isinstance(b, dict) and b.get("type") == "text":
                        parts.append(b.get("text", ""))
    return "\n".join(p for p in parts if p)


def _is_real_claude_prompt(rec: dict) -> bool:
    if rec.get("type") != "user":
        return False
    msg = rec.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        if not content:
            return False
        return not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
    return False


def _parse_codex_exit_code(output: str) -> int | None:
    if not output:
        return None
    m = CODEX_EXIT_CODE_RE.search(output)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _codex_nested_command_receipts(output: str) -> list[dict[str, Any]]:
    """Decode printed command transport receipts, never JSON inside their output."""
    receipts: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    text = output or ""
    consumed_until = 0
    for match in re.finditer(r"(?m)^[ \t]*[\[{]", text):
        start = match.end() - 1
        if start < consumed_until:
            continue
        try:
            value, consumed_until = decoder.raw_decode(text, start)
        except (ValueError, TypeError):
            continue
        # Skip the entire decoded value; nested command output is untrusted data.
        values = value if isinstance(value, list) else [value]
        for value_index, row in enumerate(values):
            receipt_index = value_index if isinstance(value, list) else None
            # The standard indexed allSettled printer nests the settlement
            # under result. Only unwrap this transport envelope, never output.
            if (isinstance(row, dict) and isinstance(row.get("i"), int)
                    and not isinstance(row.get("i"), bool)
                    and isinstance(row.get("result"), dict)):
                receipt_index = row["i"]
                row = {**row["result"], "i": receipt_index}
            if isinstance(row, dict) and row.get("status") == "fulfilled" and isinstance(row.get("value"), dict):
                receipt_index = row.get("i", receipt_index)
                row = row["value"]
            elif (isinstance(row, dict) and row.get("status") == "rejected"
                  and "reason" in row and isinstance(row.get("i", receipt_index), int)):
                receipts.append({"exit_code": 1, "output": str(row["reason"]),
                                 "settled_status": "rejected", "receipt_index": row.get("i", receipt_index)})
                continue
            if not isinstance(row, dict) or not isinstance(row.get("output"), str):
                continue
            if not isinstance(row.get("wall_time_seconds"), (int, float)):
                continue
            if not any(key in row for key in ("chunk_id", "session_id", "exit_code")):
                continue
            code = row.get("exit_code")
            if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
                continue
            if code is None and row.get("session_id") is None:
                continue
            receipts.append({**row, **({"receipt_index": receipt_index} if receipt_index is not None else {})})
    return receipts


def _codex_tool_outcome(name: str, output: str, exit_code: int | None,
                        is_error: bool) -> tuple[int | None, bool, bool]:
    """Aggregate explicit command outcomes independently of script completion."""
    if name.rsplit(".", 1)[-1] not in {"exec", "wait"}:
        pending = exit_code is None and bool(re.search(
            r"(?m)^\s*Process running with session ID \d+", output or ""
        ))
        return exit_code, is_error, pending
    receipts = _codex_nested_command_receipts(output)
    codes = [row["exit_code"] for row in receipts if row.get("exit_code") is not None]
    failures = [code for code in codes if code != 0]
    pending = any(row.get("exit_code") is None and row.get("session_id") is not None for row in receipts)
    pending = pending or bool(re.search(
        r"(?m)^\s*(?:Process running with session ID \d+|Script running with cell ID \S+)", output or ""
    ))
    if failures:
        return failures[0], True, pending
    if is_error or (exit_code is not None and exit_code != 0):
        return exit_code, True, pending
    if pending:
        return None, False, True
    return (0 if codes else exit_code), False, False


def parse_claude_session(path: Path) -> list[Turn]:
    try:
        stat = path.stat()
        file_size = stat.st_size
        file_mtime = _dt.datetime.fromtimestamp(stat.st_mtime, _dt.timezone.utc).isoformat()
    except Exception:
        file_size = None
        file_mtime = None

    records: list[tuple[int, dict]] = []
    with path.open() as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append((i, json.loads(line)))
            except Exception:
                continue

    session_id = ""
    cwd: str | None = None
    for _, r in records:
        if not session_id and r.get("sessionId"):
            session_id = r["sessionId"]
        if cwd is None and r.get("cwd"):
            cwd = r["cwd"]
        if session_id and cwd:
            break

    # Sequential grouping: a "real prompt" user record opens a turn; every record
    # that follows belongs to that turn until the next real prompt opens a new one.
    # Assistant records carry tool_use blocks but no promptId, so promptId-only grouping
    # would orphan every tool call.
    turn_groups: list[list[tuple[int, dict]]] = []
    cur_group: list[tuple[int, dict]] | None = None
    for idx, r in records:
        if _is_real_claude_prompt(r):
            cur_group = [(idx, r)]
            turn_groups.append(cur_group)
        elif cur_group is not None:
            cur_group.append((idx, r))

    turns: list[Turn] = []
    n_groups = len(turn_groups)
    for ti, recs in enumerate(turn_groups, start=1):
        pid = (recs[0][1].get("promptId") if recs else "") or f"turn_{ti}"
        prompt_text = ""
        prompt_ts: str | None = None
        completed_ts: str | None = None
        assistant_parts: list[str] = []
        assistant_events: list[AssistantEvent] = []
        tool_events: list[ToolEvent] = []
        pending: dict[str, tuple[dict, int, str | None, str]] = {}
        source_indices: list[int] = []
        last_stop_reason: str | None = None
        prompt_record_idx: int | None = None
        last_assistant_idx: int | None = None

        for idx, r in recs:
            source_indices.append(idx)
            rtype = r.get("type")
            ts = r.get("timestamp")
            if rtype == "user":
                msg = r.get("message") or {}
                content = msg.get("content")
                if not prompt_text and _is_real_claude_prompt(r):
                    prompt_text = _flatten_claude_content(content)
                    prompt_ts = ts
                    prompt_record_idx = idx
                if isinstance(content, list):
                    for c in content:
                        if not isinstance(c, dict) or c.get("type") != "tool_result":
                            continue
                        tuid = c.get("tool_use_id")
                        inner = c.get("content")
                        if isinstance(inner, str):
                            output_text = inner
                        elif isinstance(inner, list):
                            output_text = _flatten_claude_content(inner)
                        else:
                            output_text = ""
                        is_error = bool(c.get("is_error"))
                        if tuid and tuid in pending:
                            tool_input, src_idx, used_ts, name = pending.pop(tuid)
                            tool_events.append(ToolEvent(
                                index=0,
                                name=name,
                                input=tool_input,
                                tool_call_id=tuid,
                                started_at=used_ts,
                                completed_at=ts,
                                duration_ms=_iso_diff_ms(used_ts, ts),
                                is_error=is_error,
                                output_text=output_text,
                                output_char_count=len(output_text),
                                output_sha256_16=_sha16(output_text),
                                source_record_indices=[src_idx, idx],
                            ))
                        else:
                            tool_events.append(ToolEvent(
                                index=0,
                                name="?",
                                input={},
                                tool_call_id=tuid,
                                started_at=None,
                                completed_at=ts,
                                duration_ms=None,
                                is_error=is_error,
                                output_text=output_text,
                                output_char_count=len(output_text),
                                output_sha256_16=_sha16(output_text),
                                source_record_indices=[idx],
                            ))
            elif rtype == "assistant":
                msg = r.get("message") or {}
                content = msg.get("content") or []
                completed_ts = ts
                last_assistant_idx = idx
                stop_reason = msg.get("stop_reason")
                if stop_reason:
                    last_stop_reason = stop_reason
                if isinstance(content, list):
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") == "text":
                            text = c.get("text", "")
                            assistant_parts.append(text)
                            if str(text).strip():
                                assistant_events.append(AssistantEvent(
                                    text=str(text),
                                    source_record_index=idx,
                                    timestamp=ts,
                                ))
                        elif c.get("type") == "tool_use":
                            tuid = c.get("id") or ""
                            if tuid:
                                pending[tuid] = (
                                    c.get("input") or {},
                                    idx,
                                    ts,
                                    c.get("name") or "?",
                                )

        missing_result_count = len(pending)
        for tuid, (tool_input, src_idx, used_ts, name) in pending.items():
            tool_events.append(ToolEvent(
                index=0,
                name=name,
                input=tool_input,
                tool_call_id=tuid,
                started_at=used_ts,
                completed_at=None,
                duration_ms=None,
                is_error=False,
                output_text="[no result yet — turn in progress or interrupted]",
                output_char_count=0,
                output_sha256_16="",
                source_record_indices=[src_idx],
            ))

        tool_events.sort(key=lambda e: e.started_at or e.completed_at or "")
        for i, e in enumerate(tool_events, start=1):
            e.index = i

        assistant_text = "\n".join(p for p in assistant_parts if p).strip()

        has_successor = ti < n_groups
        if has_successor:
            is_complete = True
            partial_reason: str | None = None
        elif missing_result_count > 0:
            is_complete = False
            partial_reason = f"{missing_result_count} tool call(s) without results"
        elif last_stop_reason in CLAUDE_COMPLETE_STOP_REASONS:
            is_complete = True
            partial_reason = None
        elif last_stop_reason == "tool_use":
            is_complete = False
            partial_reason = "last assistant ended with tool_use; awaiting next assistant turn"
        elif last_stop_reason is None:
            is_complete = False
            partial_reason = "no assistant stop_reason observed yet"
        else:
            is_complete = False
            partial_reason = f"unrecognized stop_reason {last_stop_reason!r}"

        source_ref = {
            "session_file": str(path),
            "session_file_size_bytes": file_size,
            "session_file_mtime_utc": file_mtime,
            "record_count_in_turn": len(source_indices),
            "prompt_record_index": prompt_record_idx,
            "completion_record_index": last_assistant_idx if is_complete else None,
            "missing_result_count": missing_result_count,
            "raw_authority": "provider_session_jsonl",
        }

        turns.append(Turn(
            provider="claude_code",
            session_id=session_id,
            session_file=str(path),
            turn_id=pid,
            turn_index=ti,
            cwd=cwd,
            started_at=prompt_ts,
            completed_at=completed_ts,
            prompt_text=prompt_text,
            prompt_char_count=len(prompt_text),
            prompt_sha256_16=_sha16(prompt_text) if prompt_text else "",
            tool_events=tool_events,
            assistant_text=assistant_text,
            assistant_events=assistant_events,
            is_complete=is_complete,
            partial_reason=partial_reason,
            last_stop_reason=last_stop_reason,
            source_record_indices=source_indices,
            source_ref=source_ref,
        ))

    return turns


def parse_codex_session(path: Path) -> list[Turn]:
    try:
        stat = path.stat()
        file_size = stat.st_size
        file_mtime = _dt.datetime.fromtimestamp(stat.st_mtime, _dt.timezone.utc).isoformat()
    except Exception:
        file_size = None
        file_mtime = None

    records: list[tuple[int, dict]] = []
    with path.open() as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                records.append((i, json.loads(line)))
            except Exception:
                continue

    session_id = ""
    cwd: str | None = None
    for _, r in records:
        if r.get("type") == "session_meta":
            p = r.get("payload") or {}
            session_id = p.get("id") or session_id
            cwd = p.get("cwd") or cwd
            break

    turns: list[Turn] = []
    cur: dict | None = None
    turn_counter = 0

    def _codex_prompt_part(state: dict, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if text.startswith("# AGENTS.md instructions") or text.startswith("<environment_context>"):
            return
        if "<INSTRUCTIONS>" in text and "project-doc" in text:
            return
        if state["prompt_parts"] and state["prompt_parts"][-1] == text:
            return
        if text in state["prompt_parts"]:
            return
        state["prompt_parts"].append(text)

    def _codex_output_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                text = _codex_output_text(item)
                if text:
                    parts.append(text)
            return "\n".join(parts)
        if isinstance(value, dict):
            for key in ("output", "text", "content"):
                if key in value:
                    text = _codex_output_text(value.get(key))
                    if text:
                        return text
            try:
                return json.dumps(value, ensure_ascii=False, sort_keys=True)
            except TypeError:
                return str(value)
        return str(value)

    def _finalize(state: dict) -> Turn:
        prompt_text = "\n\n".join(state["prompt_parts"]).strip() or state["prompt_text"]
        events: list[ToolEvent] = []
        missing_outputs = 0
        for ci, (name, args, src_idx, started, call_id) in enumerate(state["calls"], start=1):
            try:
                tool_input = json.loads(args) if args else {}
            except Exception:
                tool_input = {"_raw_arguments": args}
            patch_apply_event = state["patch_apply_events"].get(call_id)
            if patch_apply_event:
                tool_input = dict(tool_input)
                tool_input["_patch_apply_event"] = patch_apply_event
            out_info = state["outputs"].get(call_id)
            if out_info:
                out_text, out_idx, out_ts = out_info
                orchestration = name.rsplit(".", 1)[-1] in {"exec", "wait"}
                exit_code = None if orchestration and _codex_nested_command_receipts(out_text) else _parse_codex_exit_code(out_text)
                is_error = (exit_code is not None and exit_code != 0)
                exit_code, is_error, outcome_pending = _codex_tool_outcome(name, out_text, exit_code, is_error)
                events.append(ToolEvent(
                    index=ci,
                    name=name,
                    input=tool_input,
                    tool_call_id=call_id,
                    started_at=started,
                    completed_at=out_ts,
                    duration_ms=_iso_diff_ms(started, out_ts),
                    is_error=is_error,
                    output_text=out_text,
                    output_char_count=len(out_text),
                    output_sha256_16=_sha16(out_text),
                    exit_code=exit_code,
                    outcome_pending=outcome_pending,
                    source_record_indices=[src_idx, out_idx],
                ))
            else:
                missing_outputs += 1
                events.append(ToolEvent(
                    index=ci,
                    name=name,
                    input=tool_input,
                    tool_call_id=call_id,
                    started_at=started,
                    completed_at=None,
                    duration_ms=None,
                    is_error=False,
                    output_text="[no output recorded]",
                    output_char_count=0,
                    output_sha256_16="",
                    exit_code=None,
                    source_record_indices=[src_idx],
                ))

        assistant_text = state["assistant"] or "\n".join(p for p in state["assistant_parts"] if p).strip()

        is_complete = state["completed_at"] is not None
        if is_complete and missing_outputs > 0:
            partial_reason: str | None = f"{missing_outputs} function_call(s) without function_call_output"
            is_complete = False
        elif is_complete:
            partial_reason = None
        elif missing_outputs > 0:
            partial_reason = f"no task_complete; {missing_outputs} function_call(s) without output"
        else:
            partial_reason = "no task_complete event for this turn_id"

        source_ref = {
            "session_file": str(path),
            "session_file_size_bytes": file_size,
            "session_file_mtime_utc": file_mtime,
            "record_count_in_turn": len(state["source_indices"]),
            "prompt_record_index": None,
            "completion_record_index": None,
            "missing_result_count": missing_outputs,
            "raw_authority": "provider_session_jsonl",
        }

        return Turn(
            provider="codex",
            session_id=session_id,
            session_file=str(path),
            turn_id=state["turn_id"],
            turn_index=state["index"],
            cwd=cwd,
            started_at=state["started_at"],
            completed_at=state["completed_at"],
            prompt_text=prompt_text,
            prompt_char_count=len(prompt_text),
            prompt_sha256_16=_sha16(prompt_text) if prompt_text else "",
            tool_events=events,
            assistant_text=assistant_text,
            assistant_events=[
                AssistantEvent(
                    text=str(row.get("text") or ""),
                    source_record_index=int(row.get("source_record_index") or 0),
                    timestamp=row.get("timestamp"),
                )
                for row in state.get("assistant_events", [])
                if str(row.get("text") or "").strip()
            ],
            is_complete=is_complete,
            partial_reason=partial_reason,
            last_stop_reason=None,
            source_record_indices=state["source_indices"],
            source_ref=source_ref,
        )

    def _new_state(turn_id: str, started: str | None) -> dict:
        return {
            "turn_id": turn_id,
            "index": 0,
            "started_at": started,
            "completed_at": None,
            "prompt_text": "",
            "assistant": "",
            "assistant_parts": [],
            "assistant_events": [],
            "prompt_parts": [],
            "calls": [],
            "outputs": {},
            "patch_apply_events": {},
            "last_call_id": "",
            "source_indices": [],
        }

    for idx, r in records:
        rtype = r.get("type")
        ts = r.get("timestamp")
        payload = r.get("payload") or {}
        ptype = payload.get("type")

        if rtype == "event_msg" and ptype == "task_started":
            if cur is not None:
                turn_counter += 1
                cur["index"] = turn_counter
                turns.append(_finalize(cur))
            cur = _new_state(payload.get("turn_id") or f"turn_{turn_counter + 1}", ts)
            cur["source_indices"].append(idx)
        elif rtype == "event_msg" and ptype == "task_complete":
            if cur is not None:
                cur["completed_at"] = ts
                last = payload.get("last_agent_message")
                if last:
                    cur["assistant"] = last
                    if not cur["assistant_events"] or cur["assistant_events"][-1]["text"] != last:
                        cur["assistant_events"].append({
                            "text": last,
                            "source_record_index": idx,
                            "timestamp": ts,
                        })
                cur["source_indices"].append(idx)
        elif cur is not None:
            cur["source_indices"].append(idx)
            if rtype == "event_msg" and ptype == "user_message":
                _codex_prompt_part(cur, str(payload.get("message") or payload.get("text") or ""))
                continue
            if rtype == "event_msg" and ptype == "patch_apply_end":
                provider_call_id = str(payload.get("call_id") or "")
                known_call_ids = {str(row[4] or "") for row in cur["calls"]}
                call_id = provider_call_id if provider_call_id in known_call_ids else str(cur.get("last_call_id") or "")
                if call_id:
                    patch_event = cur["patch_apply_events"].setdefault(
                        call_id,
                        {"success": True, "changes": {}, "provider_event_ids": []},
                    )
                    patch_event["success"] = bool(patch_event.get("success")) and bool(payload.get("success"))
                    if isinstance(payload.get("changes"), dict):
                        patch_event["changes"].update(payload["changes"])
                    if provider_call_id:
                        patch_event["provider_event_ids"].append(provider_call_id)
                continue
            if rtype != "response_item":
                continue
            if ptype == "message":
                role = payload.get("role")
                content = payload.get("content") or []
                parts: list[str] = []
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") in ("input_text", "output_text", "text"):
                            parts.append(c.get("text", ""))
                msg_text = "\n".join(p for p in parts if p)
                if role == "user" and not cur["prompt_text"]:
                    cur["prompt_text"] = msg_text
                if role == "user":
                    _codex_prompt_part(cur, msg_text)
                elif role == "assistant":
                    if msg_text:
                        cur["assistant_parts"].append(msg_text)
                        cur["assistant_events"].append({
                            "text": msg_text,
                            "source_record_index": idx,
                            "timestamp": ts,
                        })
            elif ptype == "function_call":
                call_id = payload.get("call_id") or ""
                cur["calls"].append((
                    payload.get("name") or "?",
                    payload.get("arguments") or "",
                    idx,
                    ts,
                    call_id,
                ))
                cur["last_call_id"] = call_id
            elif ptype == "function_call_output":
                cid = payload.get("call_id") or ""
                cur["outputs"][cid] = (_codex_output_text(payload.get("output")), idx, ts)
            elif ptype == "custom_tool_call":
                call_id = payload.get("call_id") or ""
                cur["calls"].append((
                    payload.get("name") or "?",
                    payload.get("input") or "",
                    idx,
                    ts,
                    call_id,
                ))
                cur["last_call_id"] = call_id
            elif ptype == "custom_tool_call_output":
                cid = payload.get("call_id") or ""
                output = _codex_output_text(payload.get("output"))
                try:
                    out_obj = json.loads(output)
                    if isinstance(out_obj, dict) and not _codex_nested_command_receipts(output):
                        output = _codex_output_text(out_obj.get("output") or output)
                        meta = out_obj.get("metadata") or {}
                        if isinstance(meta, dict) and "exit_code" in meta:
                            output = output.rstrip() + f"\nProcess exited with code {meta.get('exit_code')}"
                except Exception:
                    pass
                cur["outputs"][cid] = (output, idx, ts)

    if cur is not None:
        turn_counter += 1
        cur["index"] = turn_counter
        turns.append(_finalize(cur))

    return turns
