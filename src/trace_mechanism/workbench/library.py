"""Translate local history into the desktop workbench's mission and activity records."""

from datetime import datetime, timezone
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .. import codex_native
from ..agent_tools import captured_turns, render_codex_context
from ..parser import _is_real_claude_prompt
from ..setup import history_root, history_roots, metadata
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
                turn_id=current if isinstance(current, str) else None,
                prompt_offset=current if isinstance(current, int) else None,
                turn_index=turns.get(current, {}).get("turn_index", len(turns) + 1),
                prompt_preview=prompt,
                is_complete=state == "finished",
                state=state,
            )
    return list(events.values()), prompt, state, turns


def observe_file(path, root, st, provider):
    """Project one recording without resolving relationships to other files."""
    meta = metadata(path)
    sid = meta.get("id")
    if meta.get("provider") != provider or not isinstance(sid, str) or not sid:
        return None
    rows, start = records(path)
    events, prompt, state, turns = summary(rows)
    head_turns = summary(records(path, head=True)[0])[3] if start else turns
    first = next(
        (t["prompt_preview"] for t in head_turns.values() if t["prompt_preview"]),
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
    sub = source.get("subagent") if isinstance(source, dict) else None
    spawn = sub.get("thread_spawn") if isinstance(sub, dict) else None
    parent = (spawn or {}).get("parent_thread_id") if isinstance(spawn, dict) else None
    parent = parent or meta.get("parent_thread_id")
    recorded_id = sid
    relative = path.relative_to(root)
    parent_file = None
    unlinked = False
    if provider == "claude" and "subagents" in relative.parts[1:-1]:
        # Claude workers can share the parent sessionId. Resolve the
        # enclosing session directory, including nested worker files.
        directory = next(d for d in path.parents if d.name == "subagents")
        owner = directory.parent
        if owner.name == sid:
            parent = sid
            parent_file = owner.parent / (sid + ".jsonl")
            sid += "/" + path.relative_to(directory).with_suffix("").as_posix()
        else:
            unlinked = True
    if not isinstance(parent, str):
        parent = None
    entry = dict(
        path=path,
        provider="claude_code" if provider == "claude" else provider,
        session_id=sid,
        recorded_id=recorded_id,
        ref=hashlib.sha256(f"{path}\0{recorded_id}".encode()).hexdigest(),
        source_file=str(relative),
        provider_archived=provider == "codex" and root.name == "archived_sessions",
        parent_file=parent_file,
        unlinked=unlinked,
        source_title=path.stem if not first else "",
        prompt_derived_title=first[:90],
        prompt_preview=prompt,
        last_activity_at=last_record_at,
        mtime_utc=iso(st.st_mtime),
        size_bytes=st.st_size,
        thread_parent=parent,
        agent_name=meta.get("agent_nickname")
        or (spawn.get("agent_nickname") if isinstance(spawn, dict) else None),
        source_mtime_ms=st.st_mtime * 1000,
        worker_state=state,
        parent_evidence=(
            "subagents_directory" if provider == "claude" else "session_metadata"
        )
        if parent
        else None,
        events=events,
        history_before=start,
    )
    # A partial tail does not establish the session's total turn count.
    entry["turn_observation"] = "bounded" if start else "complete"
    if turns:
        if start:
            for observed in turns.values():
                observed["turn_index"] = None
        turn = list(turns.values())[-1]
        entry["preferred_trace_turn"] = turn
        completed = [t for t in turns.values() if t["is_complete"]]
        if completed:
            entry["latest_completed_turn"] = completed[-1]
        if state in ("working", "tool"):
            entry["active_turn"] = turn
    return entry


class Library:
    def __init__(self):
        self.cache, self.entries = {}, {}
        self.lock = threading.RLock()
        self.conflicts = set()
        self.links = {}
        self.link_gaps = {}
        self.discovery = {}
        self.missing = {}

    def discover(self):
        fresh, entries = {}, {}
        names = {}
        discovery = {}
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
                        except (ValueError, KeyError, TypeError, RecursionError):
                            pass
            except OSError:
                pass
        for provider in ("codex", "claude"):
            roots = [p.expanduser().absolute() for p in history_roots(provider)]
            report = {
                "root": str(roots[0]),
                "roots": [str(p) for p in roots],
                "exists": any(p.is_dir() for p in roots),
                "unreadable": 0,
                "unsupported": 0,
                "recognized": 0,
                "unlinked": 0,
            }
            discovery[provider] = report

            def skipped_directory(_error):
                report["unreadable"] += 1

            def history_files():
                for location in roots:
                    if location.is_symlink():
                        report["unreadable"] += 1
                        continue
                    if location.exists():
                        root = location.resolve()
                        for folder, _, files in os.walk(
                            root, onerror=skipped_directory
                        ):
                            for name in files:
                                if name.endswith(".jsonl"):
                                    yield root, Path(folder) / name

            for root, path in history_files():
                try:
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or not path.resolve().is_relative_to(root)
                    ):
                        continue
                    st = path.stat()
                    stamp = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
                    if path in self.cache and self.cache[path][0] == stamp:
                        entry = self.cache[path][1]
                    else:
                        entry = observe_file(path, root, st, provider)
                        if entry is None:
                            report["unsupported"] += 1
                            continue
                    fresh[path] = stamp, entry
                    if provider == "codex" and entry["session_id"] in names:
                        entry = dict(entry, source_title=names[entry["session_id"]])
                    entries[entry["ref"]] = entry
                    report["recognized"] += 1
                except (OSError, ValueError, TypeError, RecursionError):
                    report["unreadable"] += 1
        by_id = defaultdict(list)
        for entry in entries.values():
            by_id[entry["provider"], entry["session_id"]].append(entry)
        conflicts = {key for key, files in by_id.items() if len(files) > 1}
        links, link_gaps = defaultdict(list), defaultdict(dict)
        for ref, cached in entries.items():
            entry = entries[ref] = cached.copy()
            key = entry["provider"], entry["session_id"]
            entry["ambiguous"] = key in conflicts
            if entry["thread_parent"]:
                parents = by_id[entry["provider"], entry["thread_parent"]]
                if entry["parent_file"]:
                    local = [
                        p
                        for p in parents
                        if p["path"].parent == entry["parent_file"].parent
                        and not p["unlinked"]
                    ]
                    exact = [p for p in local if p["path"] == entry["parent_file"]]
                    parents = exact or local
                if (
                    len(parents) == 1
                    and key not in conflicts
                    and parents[0]["ref"] != ref
                ):
                    links[parents[0]["ref"]].append(ref)
                else:
                    entry["unlinked"] = True
                    for parent in parents:
                        link_gaps[parent["ref"]][entry["session_id"]] = (
                            "ambiguous worker relationship"
                        )
            if entry["unlinked"]:
                discovery["claude" if entry["provider"] == "claude_code" else "codex"][
                    "unlinked"
                ] += 1
                entry["thread_parent"] = entry["parent_evidence"] = None
        with self.lock:
            for _, old in self.cache.values():
                if old["ref"] not in entries and old.get("thread_parent"):
                    self.missing[old["ref"]] = {
                        k: old[k]
                        for k in (
                            "provider",
                            "session_id",
                            "thread_parent",
                            "parent_file",
                            "ref",
                        )
                    }
            for ref in entries:
                self.missing.pop(ref, None)
            for missing in self.missing.values():
                for parent in by_id[missing["provider"], missing["thread_parent"]]:
                    if (
                        missing["parent_file"]
                        and missing["parent_file"].parent != parent["path"].parent
                    ):
                        continue
                    if not any(
                        entries[ref]["session_id"] == missing["session_id"]
                        for ref in links[parent["ref"]]
                    ):
                        link_gaps[parent["ref"]][missing["session_id"]] = (
                            "unavailable since discovery"
                        )
            self.links, self.link_gaps = links, link_gaps
            self.cache, self.entries, self.conflicts, self.discovery = (
                fresh,
                entries,
                conflicts,
                discovery,
            )
        return [
            dict(
                (k, v)
                for k, v in e.items()
                if k not in ("path", "events", "parent_file")
            )
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
                [self.entries[ref] for ref in self.links.get(e["ref"], ())],
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
                    last_activity_at=c["last_activity_at"],
                    events=c["events"][-6:],
                    source_mtime_ms=c["source_mtime_ms"],
                )
            )
        now = time.time() * 1000
        return dict(
            ok=True,
            events=events[-12:],
            worker_state=state,
            last_activity_at=next(
                (
                    r["timestamp"]
                    for _, r in reversed(rows)
                    if isinstance(r.get("timestamp"), str)
                ),
                None,
            ),
            source_mtime_ms=e["path"].stat().st_mtime * 1000,
            sampled_at_ms=now,
            history_before=events[-12]["source_offset"] if len(events) > 12 else start,
            has_more=len(events) > 12 or bool(start),
            history=before is not None,
            team=dict(
                ok=True,
                total=len(children),
                omitted=len(children) - len(workers),
                discovery_limited=bool(self.link_gaps.get(e["ref"])),
                workers=workers,
                sampled_at_ms=now,
            ),
        )

    def capture_graph(self, root):
        """Traverse only edges observed in this discovery. Preserve known gaps separately."""
        with self.lock:
            group, seen, gaps = [root], {root["ref"]}, {}
            for parent in group:
                gaps.update(self.link_gaps.get(parent["ref"], {}))
                children = self.children(parent)
                for child in children:
                    if child["ref"] in seen:
                        gaps[child["session_id"]] = "cyclic parent relationship"
                        continue
                    seen.add(child["ref"])
                    group.append(child)
        return group, gaps

    def capture_options(self, data):
        group, gaps = self.capture_graph(self.select(data))
        return {
            "sources": [
                dict(
                    ref=e["ref"],
                    session_id=e["session_id"],
                    parent=e["thread_parent"],
                    source_file=e["source_file"],
                    provider_archived=e["provider_archived"],
                    title=e["source_title"] or e["prompt_derived_title"],
                    bytes=e["size_bytes"],
                    modified=e["mtime_utc"],
                    readable=e["size_bytes"] <= codex_native.MAX_SOURCE_BYTES,
                )
                for e in group
            ],
            "unavailable": gaps,
            "limit": 64,
        }

    def trace(self, data):
        e = self.select(data)
        turns = data.get("turns", 0)
        if type(turns) is not int or not 0 <= turns <= 10000:
            raise ValueError("Invalid turn count.")
        detail = data.get("depth") != "summary"
        closeout = data.get("closeout") is True
        tail_only = data.get("activity_only") is True
        group, gaps = (
            ([e], {}) if turns or closeout or tail_only else self.capture_graph(e)
        )
        total = len(group)
        chosen = data.get("selected_refs")
        if chosen is not None:
            if (
                turns
                or closeout
                or tail_only
                or not isinstance(chosen, list)
                or not all(isinstance(ref, str) for ref in chosen)
            ):
                raise ValueError("Choose sessions for a whole-conversation capture.")
            requested = set(chosen)
            if (
                not requested
                or len(requested) != len(chosen)
                or not requested <= {c["ref"] for c in group}
            ):
                raise ValueError("Selection changed. Choose the conversations again.")
            group = [c for c in group if c["ref"] in requested]
        elif gaps:
            raise ValueError(
                "A linked worker is unavailable or has conflicting history files. Use Choose sessions to capture the available sources."
            )
        stats = {}
        for item in group:
            self.check_path(item)
            stats[item["path"]] = item["path"].stat()
        if not tail_only and (
            len(group) > 64
            or sum(st.st_size for st in stats.values()) > codex_native.MAX_SOURCE_BYTES
        ):
            raise ValueError(
                "A capture supports 64 sessions and 256 MiB of input in total. Use Choose sessions or preview recent activity."
            )
        texts, snapshots, paths, sources, warnings = [], [], {}, [], []
        unknown_coverage = False
        if not (turns or closeout or tail_only):
            report = self.discovery.get(
                "claude" if e["provider"] == "claude_code" else "codex", {}
            )
            unknown_coverage = bool(
                report.get("unreadable")
                or report.get("unsupported")
                or report.get("unlinked")
            )
            if unknown_coverage:
                warnings.append(
                    "Some recordings could not be identified; their relationships are unknown."
                )
        for item in group:
            self.check_path(item)
            path = item["path"]
            sid = item["session_id"]
            st = stats[path]
            if metadata(path).get("id") != item["recorded_id"]:
                raise ValueError("Source identity changed. Refresh the list.")
            sources.append(
                dict(
                    ref=item["ref"],
                    source_file=item["source_file"],
                    recorded_id=item["recorded_id"],
                    provider_archived=item["provider_archived"],
                    session_id=sid,
                    title=item["source_title"] or item["prompt_derived_title"],
                    parent=item["thread_parent"],
                    relationship=item["parent_evidence"],
                    modified=iso(st.st_mtime),
                )
            )
            if tail_only:
                rows, start = records(path)
                events, prompt, state, _ = summary(rows)
                lines = [
                    f"Recent recorded activity · {sid}",
                    f"Source bytes {start}–{st.st_size} · observed state {state}",
                ]
                if prompt:
                    lines.append(f"Prompt excerpt: {prompt}")
                lines.extend(
                    f"Byte {ev['source_offset']} · {ev['label']} · {ev['status']}"
                    for ev in events
                )
                if not rows:
                    lines.append("No complete record in this byte range.")
                texts.append("\n".join(lines))
                warnings.append(
                    "Activity summary only · last 128 KiB of the selected source · message and tool bodies excluded"
                )
            elif item["provider"] == "codex":
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
        for path, before in stats.items():
            after = path.stat()
            if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) != (
                after.st_dev,
                after.st_ino,
                after.st_mtime_ns,
                after.st_size,
            ):
                raise ValueError(
                    "A selected source changed during capture. Refresh and try again."
                )
        if chosen is not None:
            warnings.extend(f"{sid}: {reason}" for sid, reason in gaps.items())
            if total > len(group):
                warnings.append(
                    f"{total - len(group)} discovered session(s) excluded by selection"
                )
        encoded = text.encode()
        return dict(
            ok=True,
            text=text,
            bytes=len(encoded),
            sessions=len(group),
            discovered=total,
            coverage=dict(
                selected=len(group),
                discovered=total,
                excluded=total - len(group),
                relationships="unknown"
                if unknown_coverage
                else "known_gaps"
                if gaps
                else "discovered",
                scope="source" if turns or closeout or tail_only else "tree",
            ),
            unavailable=gaps,
            captured_at=iso(time.time()),
            sources=sources,
            warnings=warnings,
            text_sha256=hashlib.sha256(encoded).hexdigest(),
        )
