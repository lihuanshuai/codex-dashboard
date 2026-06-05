from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .parser import codex_home, parse_conversation_file, parse_tasks, summarize

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


def create_app(codex_home_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="Codex Dashboard")
    app.state.codex_home = Path(codex_home_path or codex_home()).expanduser()
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

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    return app


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
