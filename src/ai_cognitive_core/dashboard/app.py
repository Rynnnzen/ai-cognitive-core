"""Lightweight dashboard web backend for ai_cognitive_core (v0.6.1).

Local-only by design: this app binds to 127.0.0.1 and has NO
authentication. It is meant to run on the same machine (or VM) as the
cognitive module itself, for example behind a local browser or an
``Add to Home Screen`` PWA shortcut. Do NOT expose it publicly and do
NOT bind it to 0.0.0.0 — the memory editor can rewrite Markdown memory
files, and the status endpoint exposes live cognitive state.

Endpoints
---------
GET  /                 the static dashboard UI (``dashboard/static/``)
GET  /api/status       cognitive status + Drive last-sync info
GET  /api/graph        episode / entity memory graph
GET  /api/memories     list of Markdown memory files
GET  /api/memory       one memory file (``?path=...``)
PUT  /api/memory       save a memory file (``{"path", "content"}``)

State and workspace locations come from the ``COGNITIVE_STATE_DIR``
and ``COGNITIVE_WORKSPACE_DIR`` environment variables (see
``dashboard.helpers``); they default to ``~/.ai_cognitive_state`` and
the current working directory. No user-specific local path is
hardcoded here.

Run it with::

    python -m ai_cognitive_core.dashboard.app

which serves on http://127.0.0.1:8000 (override the port with
``COGNITIVE_DASHBOARD_PORT``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from ai_cognitive_core import __version__
from ai_cognitive_core.dashboard import helpers

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as _fastapi_import_error:  # FastAPI is optional for the core.
    _FASTAPI_IMPORT_ERROR = _fastapi_import_error
    FastAPI = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    FileResponse = None  # type: ignore[assignment]
    JSONResponse = None  # type: ignore[assignment]
    StaticFiles = None  # type: ignore[assignment]


def _status_payload(state_dir: Path, workspace_dir: Path) -> dict:
    """Build the /api/status payload, never failing on partial state."""
    try:
        state = helpers.read_heart_state(state_dir)
    except Exception:
        state = {}
    try:
        sync_meta = helpers.read_sync_meta(state_dir)
    except Exception:
        sync_meta = {
            "last_sync_utc": None,
            "ago_seconds": None,
            "ago_human": "tidak diketahui",
        }
    total_turns = 0
    try:
        total_turns = int(state.get("total_turns") or 0)
    except (TypeError, ValueError):
        total_turns = 0
    if total_turns <= 0:
        # Fall back to the turn_markers table when heart state is empty.
        total_turns = helpers.count_rows(state_dir, "turn_markers")
    try:
        return helpers.build_status(state, sync_meta, total_turns, __version__)
    except Exception:
        # Last-resort minimal payload: the endpoint must never 500.
        return helpers.build_status({}, sync_meta, total_turns, __version__)


def create_app(
    state_dir: Optional[Any] = None, workspace_dir: Optional[Any] = None
) -> "FastAPI":
    """Create the dashboard FastAPI application.

    ``state_dir`` / ``workspace_dir`` override the
    ``COGNITIVE_STATE_DIR`` / ``COGNITIVE_WORKSPACE_DIR`` environment
    variables; when both are omitted the env vars (or their safe
    defaults) are used.
    """
    if FastAPI is None:
        raise ImportError(
            "FastAPI is required for the ai_cognitive_core dashboard but is "
            "not installed. Install it with: pip install fastapi uvicorn"
        ) from _FASTAPI_IMPORT_ERROR

    resolved_state = helpers.resolve_state_dir(state_dir)
    resolved_workspace = helpers.resolve_workspace_dir(workspace_dir)

    app = FastAPI(title="ai_cognitive_core dashboard", version=__version__)

    @app.get("/api/status")
    def get_status() -> dict:
        return _status_payload(resolved_state, resolved_workspace)

    @app.get("/api/graph")
    def get_graph(limit: int = helpers.GRAPH_DEFAULT_LIMIT) -> dict:
        return helpers.get_graph(resolved_state, limit=limit)

    @app.get("/api/memories")
    def get_memories() -> dict:
        try:
            memories = helpers.list_memory_files(resolved_workspace)
        except Exception:
            memories = []
        return {"memories": memories}

    @app.get("/api/memory")
    def get_memory(path: str = "") -> JSONResponse:
        try:
            payload = helpers.read_memory_file(resolved_workspace, path)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        except FileNotFoundError as exc:
            return JSONResponse(status_code=404, content={"detail": str(exc)})
        except OSError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        return JSONResponse(status_code=200, content=payload)

    @app.put("/api/memory")
    async def put_memory(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400, content={"detail": "request body must be JSON"}
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                status_code=400, content={"detail": "request body must be a JSON object"}
            )
        rel_path = payload.get("path")
        content = payload.get("content")
        if not isinstance(rel_path, str) or not rel_path:
            return JSONResponse(
                status_code=400, content={"detail": "field 'path' is required"}
            )
        if not isinstance(content, str):
            return JSONResponse(
                status_code=400, content={"detail": "field 'content' is required"}
            )
        try:
            result = helpers.write_memory_file(resolved_workspace, rel_path, content)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        except OSError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        return JSONResponse(status_code=200, content=result)

    # The static UI is mounted at /static (matching the /static/* URLs in
    # index.html); GET / serves index.html explicitly. The /api/* routes
    # above are registered first, so they always win over the static mount.
    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/")
        def ui_index() -> "FileResponse":
            return FileResponse(static_dir / "index.html")
    else:

        @app.get("/")
        def ui_not_built() -> dict:
            return {"detail": "dashboard UI not built"}

    return app


def main() -> None:
    """Serve the dashboard on 127.0.0.1:8000 (local-only, no auth)."""
    import uvicorn

    host = os.environ.get("COGNITIVE_DASHBOARD_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("COGNITIVE_DASHBOARD_PORT", "8000"))
    except ValueError:
        port = 8000
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
