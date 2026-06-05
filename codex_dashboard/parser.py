from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field, computed_field


class ApprovalRequest(BaseModel):
    call_id: str
    tool: str
    command: str = ""
    justification: str = ""
    status: str = "pending"
    requested_at: str | None = None
    resolved_at: str | None = None
    output_preview: str = ""


class TaskTurn(BaseModel):
    id: str
    session_id: str
    source: str
    file: str
    cwd: str | None = None
    originator: str | None = None
    cli_version: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    status: str = "running"
    user_message: str = ""
    session_title: str = ""
    last_agent_message: str = ""
    model_context_window: int | None = None
    collaboration_mode: str | None = None
    token_total: int | None = None
    token_input: int | None = None
    token_output: int | None = None
    function_calls: int = 0
    shell_calls: int = 0
    tool_names: dict[str, int] = Field(default_factory=dict)
    approval_requests: list[ApprovalRequest] = Field(default_factory=list)
    error: str | None = None

    @computed_field
    @property
    def project(self) -> str:
        return project_name(self.cwd)

    @computed_field
    @property
    def approval_pending_count(self) -> int:
        return sum(1 for request in self.approval_requests if request.status == "pending")

    @computed_field
    @property
    def approval_denied_count(self) -> int:
        return sum(1 for request in self.approval_requests if request.status == "denied")


class ConversationMessage(BaseModel):
    role: str
    text: str
    timestamp: str | None = None
    turn_id: str | None = None
    phase: str | None = None


class ConversationThread(BaseModel):
    session_id: str
    file: str
    cwd: str | None = None
    originator: str | None = None
    messages: list[ConversationMessage] = Field(default_factory=list)

    @computed_field
    @property
    def project(self) -> str:
        return project_name(self.cwd)


def codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def project_name(cwd: str | None) -> str:
    if not cwd:
        return "未知项目"
    name = Path(cwd).name
    return name or cwd


def extract_session_title(message: str) -> str:
    text = _trim_text(message)
    if not text:
        return ""

    request_marker = "## My request for Codex:"
    marker_index = text.rfind(request_marker)
    if marker_index >= 0:
        text = text[marker_index + len(request_marker) :]

    lines = [_trim_text(line) for line in text.splitlines()]
    useful_lines = [
        line
        for line in lines
        if line
        and not line.startswith("# In app browser:")
        and not line.startswith("# Diff comments:")
        and not line.startswith("## Comment ")
        and not line.startswith("File: ")
        and not line.startswith("Side: ")
        and not line.startswith("Lines: ")
        and not line.startswith("Comment:")
    ]
    return _clean_title_text("\n".join(useful_lines))


def discover_session_files(home: Path | None = None, include_archived: bool = True) -> list[tuple[Path, str]]:
    base = home or codex_home()
    roots: list[tuple[Path, str]] = [(base / "sessions", "active")]
    if include_archived:
        roots.append((base / "archived_sessions", "archived"))

    files: list[tuple[Path, str]] = []
    for root, source in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsonl"):
            if path.is_file():
                files.append((path, source))
    files.sort(key=lambda item: item[0].stat().st_mtime, reverse=True)
    return files


def parse_tasks(
    home: Path | None = None,
    *,
    limit: int = 200,
    include_archived: bool = True,
    max_files: int = 400,
) -> list[TaskTurn]:
    tasks: list[TaskTurn] = []
    files = discover_session_files(home, include_archived=include_archived)[:max_files]
    for path, source in files:
        tasks.extend(parse_session_file(path, source=source))
        if len(tasks) >= limit * 3:
            # A buffer keeps sorting by actual start time accurate without scanning everything.
            break

    tasks.sort(key=lambda task: _sort_time(task.updated_at, task.completed_at, task.started_at), reverse=True)
    return tasks[:limit]


def parse_session_file(path: Path, *, source: str) -> list[TaskTurn]:
    session_id = path.stem
    cwd = None
    originator = None
    cli_version = None
    current_turn: TaskTurn | None = None
    turns: dict[str, TaskTurn] = {}
    session_title = ""
    last_session_usage = {"total": 0, "input": 0, "output": 0}
    turn_baselines: dict[str, dict[str, int]] = {}
    approvals_by_call_id: dict[str, ApprovalRequest] = {}
    approval_tasks_by_call_id: dict[str, TaskTurn] = {}

    try:
        fh: Iterable[str] = path.open("r", encoding="utf-8")
    except OSError as exc:
        return [
            TaskTurn(
                id=f"unreadable:{path}",
                session_id=session_id,
                source=source,
                file=str(path),
                status="error",
                error=str(exc),
            )
        ]

    with fh:
        for raw in fh:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue

            typ = item.get("type")
            payload = item.get("payload") or {}
            item_time = _from_epoch_or_iso(None, item.get("timestamp"))
            if typ == "session_meta":
                meta = payload
                session_id = meta.get("id") or session_id
                cwd = meta.get("cwd") or cwd
                originator = meta.get("originator") or originator
                cli_version = meta.get("cli_version") or cli_version
                continue

            if typ == "turn_context":
                turn_id = payload.get("turn_id")
                if turn_id and turn_id in turns:
                    task = turns[turn_id]
                    task.cwd = payload.get("cwd") or task.cwd or cwd
                continue

            if typ == "event_msg":
                event_type = payload.get("type")
                if event_type == "task_started":
                    turn_id = payload.get("turn_id") or f"turn:{len(turns)+1}:{path}"
                    current_turn = turns.get(turn_id)
                    if current_turn is None:
                        current_turn = TaskTurn(
                            id=turn_id,
                            session_id=session_id,
                            source=source,
                            file=str(path),
                            cwd=cwd,
                            originator=originator,
                            cli_version=cli_version,
                        )
                        turns[turn_id] = current_turn
                    current_turn.status = "running"
                    current_turn.started_at = _from_epoch_or_iso(payload.get("started_at"), item.get("timestamp"))
                    current_turn.updated_at = current_turn.started_at or item_time
                    current_turn.model_context_window = payload.get("model_context_window")
                    current_turn.collaboration_mode = payload.get("collaboration_mode_kind")
                    turn_baselines[turn_id] = dict(last_session_usage)
                elif event_type == "user_message" and current_turn:
                    current_turn.user_message = _clean_text(payload.get("message") or current_turn.user_message)
                    current_turn.updated_at = item_time or current_turn.updated_at
                    if current_turn.user_message and not session_title:
                        session_title = extract_session_title(payload.get("message") or current_turn.user_message)
                elif event_type == "agent_message" and current_turn:
                    current_turn.last_agent_message = _clean_text(payload.get("message") or current_turn.last_agent_message)
                    current_turn.updated_at = item_time or current_turn.updated_at
                elif event_type == "token_count" and current_turn:
                    last_session_usage = _apply_token_count(
                        current_turn,
                        payload,
                        baseline=turn_baselines.get(current_turn.id),
                        previous_session_usage=last_session_usage,
                    )
                    current_turn.updated_at = item_time or current_turn.updated_at
                elif event_type == "task_complete":
                    turn_id = payload.get("turn_id")
                    task = turns.get(turn_id) if turn_id else current_turn
                    if task:
                        task.status = "completed"
                        task.completed_at = _from_epoch_or_iso(payload.get("completed_at"), item.get("timestamp"))
                        task.updated_at = task.completed_at or item_time or task.updated_at
                        task.duration_ms = payload.get("duration_ms")
                        task.last_agent_message = _clean_text(
                            payload.get("last_agent_message") or task.last_agent_message
                        )
                    if current_turn and task and current_turn.id == task.id:
                        current_turn = task
                continue

            if typ == "response_item" and current_turn:
                rtype = payload.get("type")
                current_turn.updated_at = item_time or current_turn.updated_at
                if rtype == "function_call":
                    name = str(payload.get("name") or "unknown")
                    current_turn.function_calls += 1
                    current_turn.tool_names[name] = current_turn.tool_names.get(name, 0) + 1
                    if name == "exec_command":
                        current_turn.shell_calls += 1
                    approval = _extract_approval_request(payload, item.get("timestamp"))
                    if approval:
                        current_turn.approval_requests.append(approval)
                        approvals_by_call_id[approval.call_id] = approval
                        approval_tasks_by_call_id[approval.call_id] = current_turn
                elif rtype == "function_call_output":
                    call_id = str(payload.get("call_id") or "")
                    approval = approvals_by_call_id.get(call_id)
                    if approval:
                        output = str(payload.get("output") or "")
                        approval.status = _approval_status_from_output(output)
                        approval.resolved_at = _from_epoch_or_iso(None, item.get("timestamp"))
                        approval.output_preview = _clean_text(output)[:240]
                        approval_task = approval_tasks_by_call_id.get(call_id)
                        if approval_task:
                            approval_task.updated_at = item_time or approval_task.updated_at
                elif rtype == "message" and payload.get("role") == "user" and not current_turn.user_message:
                    current_turn.user_message = _clean_text(_extract_content_text(payload.get("content")))
                elif rtype == "message" and payload.get("role") == "assistant":
                    text = _extract_content_text(payload.get("content"))
                    if text:
                        current_turn.last_agent_message = _clean_text(text)

    for task in turns.values():
        task.session_title = session_title
    return list(turns.values())


def parse_conversation_file(path: Path) -> ConversationThread:
    session_id = path.stem
    cwd = None
    originator = None
    current_turn_id = None
    messages: list[ConversationMessage] = []

    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue

            typ = item.get("type")
            payload = item.get("payload") or {}
            timestamp = item.get("timestamp")
            if typ == "session_meta":
                session_id = payload.get("id") or session_id
                cwd = payload.get("cwd") or cwd
                originator = payload.get("originator") or originator
                continue

            if typ == "event_msg":
                event_type = payload.get("type")
                if event_type == "task_started":
                    current_turn_id = payload.get("turn_id") or current_turn_id
                elif event_type == "user_message":
                    text = _trim_text(payload.get("message") or "")
                    if text:
                        messages.append(
                            ConversationMessage(
                                role="user",
                                text=text,
                                timestamp=timestamp,
                                turn_id=current_turn_id,
                            )
                        )
                continue

            if typ != "response_item":
                continue

            if payload.get("type") != "message":
                continue

            role = payload.get("role")
            if role == "assistant":
                text = _trim_text(_extract_content_text(payload.get("content")))
                if text:
                    messages.append(
                        ConversationMessage(
                            role="assistant",
                            text=text,
                            timestamp=timestamp,
                            turn_id=current_turn_id,
                            phase=payload.get("phase"),
                        )
                    )

    return ConversationThread(
        session_id=session_id,
        cwd=cwd,
        originator=originator,
        file=str(path),
        messages=messages,
    )


def summarize(tasks: list[TaskTurn]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    active_cwds: dict[str, int] = {}
    by_project: dict[str, int] = {}
    approvals = {"total": 0, "pending": 0, "approved": 0, "denied": 0}
    for task in tasks:
        by_status[task.status] = by_status.get(task.status, 0) + 1
        by_source[task.source] = by_source.get(task.source, 0) + 1
        project = project_name(task.cwd)
        by_project[project] = by_project.get(project, 0) + 1
        for request in task.approval_requests:
            approvals["total"] += 1
            approvals[request.status] = approvals.get(request.status, 0) + 1
        if task.cwd:
            active_cwds[task.cwd] = active_cwds.get(task.cwd, 0) + 1

    return {
        "total": len(tasks),
        "by_status": by_status,
        "by_source": by_source,
        "by_project": by_project,
        "approvals": approvals,
        "top_projects": sorted(by_project.items(), key=lambda item: item[1], reverse=True)[:8],
        "top_cwds": sorted(active_cwds.items(), key=lambda item: item[1], reverse=True)[:8],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _apply_token_count(
    task: TaskTurn,
    payload: dict[str, Any],
    *,
    baseline: dict[str, int] | None,
    previous_session_usage: dict[str, int],
) -> dict[str, int]:
    info = payload.get("info") or {}
    total_usage = info.get("total_token_usage") or {}
    if isinstance(total_usage, dict):
        current = {
            "total": _first_int(total_usage, "total_tokens", "tokens", "total") or 0,
            "input": _first_int(total_usage, "input_tokens", "prompt_tokens") or 0,
            "output": _first_int(total_usage, "output_tokens", "completion_tokens") or 0,
        }
        base = baseline or {"total": 0, "input": 0, "output": 0}
        task.token_total = max(0, current["total"] - base["total"])
        task.token_input = max(0, current["input"] - base["input"])
        task.token_output = max(0, current["output"] - base["output"])
        return current

    usage = info.get("last_token_usage") or info.get("token_usage") or {}
    if isinstance(usage, dict):
        task.token_total = _first_int(usage, "total_tokens", "tokens", "total") or task.token_total
        task.token_input = _first_int(usage, "input_tokens", "prompt_tokens") or task.token_input
        task.token_output = _first_int(usage, "output_tokens", "completion_tokens") or task.token_output
    return previous_session_usage


def _extract_approval_request(payload: dict[str, Any], timestamp: Any) -> ApprovalRequest | None:
    arguments = _parse_arguments(payload.get("arguments"))
    if not _requires_approval(arguments):
        return None

    call_id = str(payload.get("call_id") or "")
    if not call_id:
        return None
    return ApprovalRequest(
        call_id=call_id,
        tool=str(payload.get("name") or "unknown"),
        command=str(arguments.get("cmd") or arguments.get("command") or ""),
        justification=str(arguments.get("justification") or ""),
        requested_at=_from_epoch_or_iso(None, timestamp),
    )


def _parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _requires_approval(arguments: dict[str, Any]) -> bool:
    return (
        arguments.get("sandbox_permissions") == "require_escalated"
        or arguments.get("with_escalated_permissions") is True
    )


def _approval_status_from_output(output: str) -> str:
    lowered = output.lower()
    denial_markers = (
        "rejected by user",
        "this action was rejected",
        'rejected("',
        "rejected('",
        "approval denied",
        "not approved",
        "permission denied by user",
    )
    if any(marker in lowered for marker in denial_markers):
        return "denied"
    return "approved"


def _first_int(values: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = values.get(key)
        if isinstance(value, int):
            return value
    return None


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("input_text") or part.get("output_text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return ""


def _clean_text(text: str) -> str:
    return " ".join(str(text).strip().split())


def _clean_title_text(text: str) -> str:
    without_links = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", str(text))
    return _clean_text(without_links)


def _trim_text(text: str) -> str:
    return str(text).strip()


def _from_epoch_or_iso(value: Any, fallback: Any = None) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, str) and value:
        return value
    if isinstance(fallback, str) and fallback:
        return fallback
    return None


def _sort_time(*values: str | None) -> float:
    for value in values:
        if not value:
            continue
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            continue
    return 0.0
