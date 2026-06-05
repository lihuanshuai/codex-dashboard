from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .approval_bridge import ApprovalBridgeUnavailable, CodexApprovalBridge, LiveApprovalNotFound
from .parser import ApprovalRequest, TaskTurn, codex_home, parse_conversation_file, parse_session_file, parse_tasks, summarize

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


class ApprovalDecisionBody(BaseModel):
    file: str | None = None
    session_id: str | None = None
    call_id: str
    turn_id: str | None = None
    decision: Literal["accept", "accept_for_session", "decline"]


class OpenDesktopThreadBody(BaseModel):
    thread_id: str


def create_app(codex_home_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Codex Dashboard")
    app.state.codex_home = Path(codex_home_path or codex_home()).expanduser()
    app.state.approval_bridge = CodexApprovalBridge(app.state.codex_home)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    templates = Jinja2Templates(directory=TEMPLATES_DIR)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/index.html", response_class=HTMLResponse)
    async def index(request: Request) -> Any:
        return templates.TemplateResponse(request, "index.html", {"title": "Codex Tasks"})

    @app.get("/api/tasks")
    async def tasks(
        limit: int = Query(default=120, ge=1, le=500),
        max_files: int = Query(default=500, ge=1, le=5000),
        archived: bool = True,
    ) -> dict[str, Any]:
        parsed_tasks = parse_tasks(
            app.state.codex_home,
            limit=limit,
            include_archived=archived,
            max_files=max_files,
        )
        return {
            "summary": summarize(parsed_tasks),
            "tasks": parsed_tasks,
        }

    @app.get("/api/session")
    async def session(file: str = Query(..., min_length=1)) -> Any:
        try:
            path = _resolve_session_path(app.state.codex_home, file)
            return parse_conversation_file(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/approval-bridge/status")
    async def approval_bridge_status(connect: bool = False) -> Any:
        bridge = app.state.approval_bridge
        if connect and not bridge.status().connected:
            try:
                await bridge.ensure_ready(start_if_missing=True)
            except ApprovalBridgeUnavailable:
                pass
        return bridge.status()

    @app.post("/api/approval/decision")
    async def approval_decision(request: Request, body: ApprovalDecisionBody) -> dict[str, Any]:
        _require_loopback_client(request)
        try:
            if body.file and body.session_id:
                task, approval = _find_pending_approval(app.state.codex_home, body)
                await app.state.approval_bridge.decide(
                    call_id=approval.call_id,
                    decision=body.decision,
                    thread_id=task.session_id,
                    turn_id=task.id,
                )
            else:
                await app.state.approval_bridge.decide(
                    call_id=body.call_id,
                    decision=body.decision,
                    turn_id=body.turn_id,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LiveApprovalNotFound as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ApprovalBridgeUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"ok": True, "message": "审批决定已发送给 Codex app-server。"}

    @app.post("/api/desktop/open-thread")
    async def open_desktop_thread(request: Request, body: OpenDesktopThreadBody) -> dict[str, Any]:
        _require_loopback_client(request)
        thread_id = _normalize_thread_id(body.thread_id)
        try:
            await _open_codex_thread(thread_id)
        except OSError as exc:
            raise HTTPException(status_code=503, detail=f"无法打开 Codex Desktop：{exc}") from exc
        return {"ok": True, "message": "已请求 Codex Desktop 打开原会话。"}

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


def _require_loopback_client(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="This action is only allowed from localhost")


def _normalize_thread_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Codex thread id") from exc


async def _open_codex_thread(thread_id: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/open",
        f"codex://threads/{thread_id}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
        raise OSError(detail or f"/usr/bin/open exited with {process.returncode}")


def _find_pending_approval(home: Path, body: ApprovalDecisionBody) -> tuple[TaskTurn, ApprovalRequest]:
    path = _resolve_session_path(home, body.file)
    source = "archived" if _is_archived_session_file(home, path) else "active"
    for task in parse_session_file(path, source=source):
        if task.session_id != body.session_id:
            continue
        if body.turn_id and task.id != body.turn_id:
            continue
        for approval in task.approval_requests:
            if approval.call_id != body.call_id:
                continue
            if approval.status != "pending":
                raise HTTPException(status_code=409, detail="Approval request is no longer pending")
            return task, approval
    raise HTTPException(status_code=404, detail="Pending approval request was not found")


def _is_archived_session_file(home: Path, path: Path) -> bool:
    archived_root = (home / "archived_sessions").expanduser().resolve()
    return path.is_relative_to(archived_root)


def _resolve_session_path(home: Path, raw_file: str) -> Path:
    path = Path(raw_file).expanduser().resolve()
    allowed_roots = [
        (home / "sessions").expanduser().resolve(),
        (home / "archived_sessions").expanduser().resolve(),
    ]
    if not any(path.is_relative_to(root) for root in allowed_roots):
        raise ValueError("Session file is outside CODEX_HOME")
    if path.suffix != ".jsonl":
        raise ValueError("Session file must be a JSONL file")
    if not path.is_file():
        raise OSError("Session file does not exist")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve a local Codex task dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind, default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind, default: 8765")
    parser.add_argument("--codex-home", default=str(codex_home()), help="Path to CODEX_HOME, default: ~/.codex")
    parser.add_argument("--quiet", action="store_true", help="Suppress HTTP access logs")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    app = create_app(args.codex_home)
    log_level = "warning" if args.quiet else "info"
    print(f"Codex dashboard: http://{args.host}:{args.port}")
    print(f"Reading sessions from: {Path(args.codex_home).expanduser()}")
    uvicorn.run(app, host=args.host, port=args.port, log_level=log_level)


app = create_app()


if __name__ == "__main__":
    main()
