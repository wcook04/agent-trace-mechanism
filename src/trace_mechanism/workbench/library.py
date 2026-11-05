"""Translate local history into the desktop workbench's mission and activity records."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time

from .. import codex_native
from ..agent_tools import captured_turns, render_codex_context
from ..parser import _is_real_claude_prompt
from ..setup import history_root, metadata
from ..views import render


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def records(path, before=None, head=False):
    """Read at most 128 KiB, including whole records only; offsets support Earlier."""
    with path.open("rb") as f:
        size = f.seek(0, 2)
        end = min(size, before) if before is not None else size
        start = 0 if head else max(0, end - 131072)
        f.seek(max(0, start - 1))
        if start and f.read(1) != b"\n":
            f.readline(end - start)
        offset = f.tell()
        chunk = f.read(min(131072, max(0, end - offset)))
    out = []
    for line in chunk.splitlines(keepends=True):
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append((offset, row))
        except (ValueError, UnicodeDecodeError, RecursionError):
            pass
        offset += len(line)
    return out, start


def summary(rows):
    events, prompt, state, turns = {}, "", "unknown", {}
    current = None
    for offset, row in rows:
        p = row.get("payload") or {}
        if not isinstance(p, dict):
            continue
        typ = p.get("type", "")
        turn = p.get("turn_id")
        if isinstance(turn, str) and turn and turn != current:
            current = turn
            state, prompt = "unknown", ""
        if typ in ("task_complete", "turn_aborted"):
            state = "finished" if typ == "task_complete" else "interrupted"
        elif typ in ("task_started", "user_message"):
            state = "working"
        msg = row.get("message") or {}
        if not isinstance(msg, dict):
            msg = {}
        content = msg.get("content")
        if typ == "user_message":
            prompt = str(p.get("message") or "")[:400]
        if (
            row.get("type") == "user"
            and isinstance(row.get("message"), dict)
            and _is_real_claude_prompt(row)
        ):
            current, state = offset, "working"
            prompt = content[:400] if isinstance(content, str) else ""
        bits = list(content) if isinstance(content, list) else []
        if typ in (
            "function_call",
            "custom_tool_call",
            "function_call_output",
            "custom_tool_call_output",
        ):
            bits.append(p)
        if typ in ("item_started", "item_completed") and isinstance(
            p.get("item"), dict
        ):
            bits.append(dict(p["item"], native_status=typ))
        for bit in bits:
            if not isinstance(bit, dict):
                continue
            kind = bit.get("type", "")
            if kind == "text" and row.get("type") == "user":
                prompt = str(bit.get("text") or "")[:400]
            result = kind in (
                "tool_result",
                "function_call_output",
                "custom_tool_call_output",
            )
            if (
                not result
                and kind not in ("tool_use", "function_call", "custom_tool_call")
                and not bit.get("native_status")
            ):
                continue
            token = str(kind).replace("_", "").lower()
            if (
                token == "agentmessage"
                and bit.get("phase") == "final_answer"
                and typ == "item_completed"
            ):
                state = "finished"
            if token == "usermessage":
                prompt, state = codex_native._message_text(bit)[:400], "working"
            if token in ("reasoning", "usermessage", "agentmessage"):
                continue
            key = str(
                bit.get("tool_use_id") or bit.get("call_id") or bit.get("id") or offset
            )
            prev = events.get(key, {})
            tool = str(
                bit.get("name")
                or prev.get("tool")
                or ("Shell" if kind == "CommandExecution" else kind)
            )
            status = (
                "failed"
                if bit.get("is_error")
                or codex_native._failed(
                    {
                        "item": {
                            **bit,
                            "exit_code": bit.get("exit_code", bit.get("exitCode")),
                        }
                    }
                )
                else "completed"
                if result or bit.get("native_status") == "item_completed"
                else "started"
            )
            args = bit.get("input")
            if not args and isinstance(bit.get("arguments"), str):
                try:
                    args = json.loads(bit["arguments"])
                except ValueError:
                    args = {}
            label = prev.get("label") or tool.replace("_", " ")
            if tool == "apply_patch":
                label = "Patch"
            elif tool in ("Shell", "Bash", "shell", "exec_command"):
                command = (
                    args.get("cmd") or args.get("command")
                    if isinstance(args, dict)
                    else None
                )
                words = command.split() if isinstance(command, str) else []
                label = (
                    Path(words[0]).name
                    if words
                    else prev.get("label", "Run shell command")
                )
            detail = (
                Path(str(args.get("file_path") or args.get("path") or "")).name
                if isinstance(args, dict)
                else prev.get("detail", "")
            )
            events[key] = dict(
                id=key,
                tool=tool,
                kind={
                    "read": "read",
                    "edit": "edit",
                    "write": "edit",
                    "grep": "search",
                }.get(tool.lower(), "shell"),
                label=label,
                status=status,
                detail=detail[:120],
                timestamp=row.get("timestamp"),
                source_offset=prev.get("source_offset", offset),
            )
            state = "tool" if status == "started" else "working"
        if row.get("type") == "assistant" and msg.get("stop_reason") in (
            "end_turn",
            "stop_sequence",
        ):
            state = "finished"
        if current is not None:
            turns[current] = dict(
                turn_index=turns.get(current, {}).get("turn_index", len(turns) + 1),
                prompt_preview=prompt,
                is_complete=state == "finished",
                state=state,
            )
    return list(events.values()), prompt, state, turns


class Library:
    def __init__(self):
        self.cache, self.entries = {}, {}
        self.lock = threading.RLock()
        self.conflicts = set()

    def discover(self):
        fresh, entries = {}, {}
        names = {}
        idx = history_root("codex").parent / "session_index.jsonl"
        if idx.is_file() and not idx.is_symlink():
            try:
                with idx.open("rb") as f:
                    for line in f:
                        try:
                            row = json.loads(line)
                            if isinstance(row, dict) and isinstance(
                                row.get("thread_name"), str
                            ):
                                names[row["id"]] = row["thread_name"]
                        except (ValueError, KeyError, TypeError):
                            pass
            except OSError:
                pass
        for provider in ("codex", "claude"):
            root = history_root(provider).expanduser().resolve()
            for path in root.rglob("*.jsonl"):
                try:
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or not path.resolve().is_relative_to(root)
                    ):
                        continue
                    st = path.stat()
                    stamp = (st.st_size, st.st_mtime_ns)
                    if path in self.cache and self.cache[path][0] == stamp:
                        entry = self.cache[path][1]
                    else:
                        meta = metadata(path)
                        sid = meta.get("id")
                        if (
                            meta.get("provider") != provider
                            or not isinstance(sid, str)
                            or not sid
                        ):
                            continue
                        rows, start = records(path)
                        events, prompt, state, turns = summary(rows)
                        head_turns = (
                            summary(records(path, head=True)[0])[3] if start else turns
                        )
                        first = next(
                            (
                                t["prompt_preview"]
                                for t in head_turns.values()
                                if t["prompt_preview"]
                            ),
                            "",
                        )
                        last_record_at = next(
                            (
                                r["timestamp"]
                                for _, r in reversed(rows)
                                if isinstance(r.get("timestamp"), str)
                            ),
                            None,
                        )
                        source = meta.get("source") or {}
                        sub = (
                            source.get("subagent") if isinstance(source, dict) else None
                        )
                        spawn = (
                            sub.get("thread_spawn") if isinstance(sub, dict) else None
                        )
                        parent = (
                            (spawn or {}).get("parent_thread_id")
                            if isinstance(spawn, dict)
                            else None
                        )
                        parent = parent or meta.get("parent_thread_id")
                        recorded_id = sid
                        if (
                            provider == "claude"
                            and path.parent.name == "subagents"
                            and path.parent.parent.name == sid
                        ):
                            parent, sid = sid, sid + "/" + path.stem
                        entry = dict(
                            path=path,
                            provider="claude_code"
                            if provider == "claude"
                            else provider,
                            session_id=sid,
                            recorded_id=recorded_id,
                            ref=hashlib.sha256(str(path).encode()).hexdigest(),
                            source_title=path.stem if not first else "",
                            prompt_derived_title=first[:90],
                            prompt_preview=prompt,
                            last_activity_at=last_record_at or iso(st.st_mtime),
                            mtime_utc=iso(st.st_mtime),
                            size_bytes=st.st_size,
                            thread_parent=parent,
                            agent_name=meta.get("agent_nickname")
                            or (spawn or {}).get("agent_nickname")
                            if isinstance(spawn, dict)
                            else None,
                            source_mtime_ms=st.st_mtime * 1000,
                            worker_state=state,
                            parent_evidence=(
                                "subagents_directory"
                                if provider == "claude"
                                else "session_metadata"
                            )
                            if parent
                            else None,
                            events=events,
                            history_before=start,
                        )
                        # A partial tail does not establish the session's total turn count.
                        if not start and turns:
                            turn = list(turns.values())[-1]
                            entry["preferred_trace_turn"] = turn
                            completed = [t for t in turns.values() if t["is_complete"]]
                            if completed:
                                entry["latest_completed_turn"] = completed[-1]
                            if state in ("working", "tool"):
                                entry["active_turn"] = turn
                    fresh[path] = stamp, entry
                    if provider == "codex" and entry["session_id"] in names:
                        entry = dict(entry, source_title=names[entry["session_id"]])
                    entries[entry["ref"]] = entry
                except (OSError, ValueError, TypeError):
                    continue
        ids = set()
        conflicts = set()
        for entry in entries.values():
            key = entry["provider"], entry["session_id"]
            if key in ids:
                conflicts.add(key)
            ids.add(key)
        entries = {
            ref: e
            for ref, e in entries.items()
            if (e["provider"], e["session_id"]) not in conflicts
        }
        with self.lock:
            self.cache, self.entries, self.conflicts = fresh, entries, conflicts
        return [
            dict((k, v) for k, v in e.items() if k not in ("path", "events"))
            for e in sorted(entries.values(), key=lambda e: -e["source_mtime_ms"])
        ]

    def select(self, data):
        with self.lock:
            if "ref" in data:
                if data["ref"] not in self.entries:
                    raise ValueError("Session moved or is ambiguous. Refresh the list.")
                e = self.entries[data["ref"]]
            else:
                hits = [
                    e
                    for e in self.entries.values()
                    if e["session_id"] == data.get("session_id")
                    and e["provider"] == data.get("provider")
                ]
                if len(hits) != 1:
                    raise ValueError("Session moved or is ambiguous. Refresh the list.")
                e = hits[0]
        self.check_path(e)
        return e

    @staticmethod
    def check_path(e):
        p = e["path"]
        if p.resolve() != p or not p.is_file():
            raise ValueError("Session moved. Refresh the list.")

    def children(self, e):
        with self.lock:
            return sorted(
                [
                    c
                    for c in self.entries.values()
                    if c["provider"] == e["provider"]
                    and c["thread_parent"] == e["session_id"]
                    and (
                        c["parent_evidence"] != "subagents_directory"
                        or c["path"].parent.parent.parent == e["path"].parent
                    )
                ],
                key=lambda c: c["session_id"],
            )

    def activity(self, data):
        e = self.select(data)
        before = data.get("history_before")
        if before is not None and (type(before) != int or before < 0):
            raise ValueError("Invalid history offset.")
        rows, start = records(e["path"], before)
        events, _, state, _ = summary(rows)
        children = self.children(e)
        workers = []
        for c in sorted(children, key=lambda c: -c["source_mtime_ms"])[:16]:
            workers.append(
                dict(
                    id=c["session_id"],
                    mission_key=f"{c['provider']}:{c['session_id']}",
                    label=c["agent_name"]
                    or c["source_title"]
                    or c["prompt_derived_title"],
                    state=c["worker_state"],
                    events=c["events"][-6:],
                    source_mtime_ms=c["source_mtime_ms"],
                )
            )
        now = time.time() * 1000
        return dict(
            ok=True,
            events=events[-12:],
            worker_state=state,
            source_mtime_ms=e["path"].stat().st_mtime * 1000,
            sampled_at_ms=now,
            history_before=events[-12]["source_offset"] if len(events) > 12 else start,
            has_more=len(events) > 12 or bool(start),
            history=before is not None,
            team=dict(
                ok=True,
                total=len(children),
                omitted=len(children) - len(workers),
                workers=workers,
                sampled_at_ms=now,
            ),
        )

    def trace(self, data):
        e = self.select(data)
        turns = data.get("turns", 0)
        if type(turns) is not int or not 0 <= turns <= 10000:
            raise ValueError("Invalid turn count.")
        detail = data.get("depth") != "summary"
        closeout = data.get("closeout") is True
        group = [e]
        if not turns and not closeout:
            seen = {e["ref"]}
            for parent in group:
                for c in self.children(parent):
                    if c["ref"] in seen:
                        raise ValueError(
                            "The selected history has a cyclic parent relationship."
                        )
                    seen.add(c["ref"])
                    group.append(c)
                    if len(group) > 64:
                        raise ValueError(
                            "More than 64 linked sessions. Choose a recent-turn scope."
                        )
        texts, snapshots, paths, sources, warnings = [], [], {}, [], []
        for item in group:
            if not turns and not closeout:
                with self.lock:
                    if any(
                        c["provider"] == item["provider"]
                        and c["thread_parent"] == item["session_id"]
                        and (c["provider"], c["session_id"]) in self.conflicts
                        for _, c in self.cache.values()
                    ):
                        raise ValueError(
                            "A linked worker has conflicting history files. Resolve the duplicate before copying."
                        )
            self.check_path(item)
            path = item["path"]
            sid = item["session_id"]
            if metadata(path).get("id") != item["recorded_id"]:
                raise ValueError("Source identity changed. Refresh the list.")
            sources.append(
                dict(
                    session_id=sid,
                    title=item["source_title"] or item["prompt_derived_title"],
                    parent=item["thread_parent"],
                    relationship=item["parent_evidence"],
                )
            )
            if item["provider"] == "codex":
                snapshot = codex_native.load_rollout(path, session_id=sid)
                snapshots.append(snapshot)
                paths[sid] = path
                for key in (
                    "pending_records",
                    "malformed_records",
                    "oversized_records",
                    "identity_mismatches",
                ):
                    count = snapshot["diagnostics"][key]
                    if count:
                        warnings.append(f"{sid}: {count} {key.replace('_', ' ')}")
            else:
                parsed, issues, finals = captured_turns(
                    path, item["recorded_id"], "claude"
                )
                warnings.extend(
                    f"{sid}: {count} {issue}" for issue, count in issues.items()
                )
                selected = parsed[-turns:] if turns else parsed
                if closeout:
                    answer = next(
                        (
                            finals[index]
                            for t in reversed(selected)
                            for index in reversed(t.source_record_indices)
                            if index in finals
                        ),
                        "",
                    )
                    if not answer:
                        raise ValueError(
                            "No completed assistant answer recorded in this scope."
                        )
                    texts.append(answer)
                else:
                    text = render(selected, detail=detail)
                    if not text:
                        raise ValueError(f"No readable turns for {sid}.")
                    texts.append(f"Session: {sid}\n{text}" if len(group) > 1 else text)
        if snapshots:
            text, _ = render_codex_context(
                snapshots,
                paths,
                detail=detail,
                turns=turns,
                closeout=closeout,
                require_readable=True,
            )
        else:
            text = "\n\n".join(texts)
        if not text:
            raise ValueError("No readable records in the selected scope.")
        encoded = text.encode()
        return dict(
            ok=True,
            text=text,
            bytes=len(encoded),
            sessions=len(group),
            sources=sources,
            warnings=warnings,
            text_sha256=hashlib.sha256(encoded).hexdigest(),
        )
