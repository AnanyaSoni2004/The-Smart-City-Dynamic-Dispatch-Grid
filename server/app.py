"""FastAPI app: live simulation streaming + saved-run replay.

    uvicorn server.app:app --reload

Endpoints:
    POST /api/runs                start a simulation, returns {id}
    GET  /api/runs                recent runs (active + saved)
    GET  /api/runs/{id}           run metadata; full timeline when complete
    WS   /api/runs/{id}/ws        live frame stream while a run is active
    /                             built React frontend (web/dist)
"""
from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .engine import SimulationSession

app = FastAPI(title="Dispatch Grid")
app.add_middleware(GZipMiddleware, minimum_size=2048)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class RunParams(BaseModel):
    duration: float = Field(3600.0, ge=300, le=7200)   # seconds of call stream
    incidents: int = Field(320, ge=10, le=600)
    seed: int = Field(42, ge=0, le=10_000_000)
    tick: float = Field(10.0, ge=5, le=60)
    speed: float = Field(120.0, ge=10, le=600)         # sim-seconds per real second
    mode: str = Field("synthetic", pattern="^(synthetic|seattle)$")


@dataclass
class ActiveRun:
    id: str
    params: RunParams
    session: SimulationSession
    graph: dict
    created_at: str
    frames: list[dict] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    done: bool = False
    summary: dict | None = None


ACTIVE: dict[str, ActiveRun] = {}
# protects the free-tier host: strangers can't pile up CPU-burning simulations
MAX_ACTIVE_RUNS = 4


async def _run_loop(run: ActiveRun) -> None:
    pace = run.params.tick / run.params.speed  # real seconds per frame
    try:
        while True:
            frame = await asyncio.to_thread(run.session.step)
            if frame is None:
                break
            run.frames.append(frame)
            for q in list(run.subscribers):
                q.put_nowait({"type": "frame", "frame": frame})
            await asyncio.sleep(pace)
        run.summary = run.session.summary()
        run.done = True
        await asyncio.to_thread(
            db.save_run, run.id, run.params.model_dump(), run.summary,
            run.graph, run.frames)
        for q in list(run.subscribers):
            q.put_nowait({"type": "done", "summary": run.summary})
    finally:
        # keep the finished run in memory briefly for late websocket joins
        await asyncio.sleep(60)
        ACTIVE.pop(run.id, None)


@app.post("/api/runs")
async def create_run(params: RunParams) -> dict:
    if sum(1 for r in ACTIVE.values() if not r.done) >= MAX_ACTIVE_RUNS:
        raise HTTPException(
            429, "All simulation slots are busy right now — watch a recent "
                 "run or try again in a minute.")
    run_id = secrets.token_hex(4)
    try:
        session = await asyncio.to_thread(
            SimulationSession, params.duration, params.tick,
            params.seed, params.incidents, params.mode)
    except Exception:
        if params.mode == "seattle":
            raise HTTPException(
                502, "Couldn't fetch live Seattle 911 data right now — "
                     "try again in a minute, or run a synthetic disaster.")
        raise
    run = ActiveRun(id=run_id, params=params, session=session,
                    graph=session.static_payload(),
                    created_at=datetime.now(timezone.utc).isoformat())
    ACTIVE[run_id] = run
    asyncio.get_running_loop().create_task(_run_loop(run))
    return {"id": run_id}


@app.get("/api/runs")
async def runs_index() -> list[dict]:
    active = [{"id": r.id, "created_at": r.created_at,
               "status": "complete" if r.done else "running",
               "params": r.params.model_dump(), "summary": r.summary}
              for r in ACTIVE.values()]
    saved = await asyncio.to_thread(db.list_runs)
    seen = {r["id"] for r in active}
    out = active + [r for r in saved if r["id"] not in seen]
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out[:30]


@app.get("/api/runs/{run_id}")
async def run_detail(run_id: str) -> dict:
    run = ACTIVE.get(run_id)
    if run is not None and not run.done:
        return {"id": run.id, "created_at": run.created_at, "status": "running",
                "params": run.params.model_dump(), "graph": run.graph,
                "summary": None, "timeline": []}
    if run is not None and run.done:
        return {"id": run.id, "created_at": run.created_at, "status": "complete",
                "params": run.params.model_dump(), "graph": run.graph,
                "summary": run.summary, "timeline": run.frames}
    saved = await asyncio.to_thread(db.get_run, run_id)
    if saved is None:
        raise HTTPException(404, "run not found")
    return saved


@app.websocket("/api/runs/{run_id}/ws")
async def run_stream(ws: WebSocket, run_id: str) -> None:
    await ws.accept()
    run = ACTIVE.get(run_id)
    if run is None:
        await ws.send_text(json.dumps({"type": "error", "error": "not_active"}))
        await ws.close()
        return
    q: asyncio.Queue = asyncio.Queue()
    run.subscribers.append(q)
    try:
        await ws.send_text(json.dumps({
            "type": "init", "params": run.params.model_dump(),
            "graph": run.graph}))
        # catch up on frames produced before this client connected
        for i in range(0, len(run.frames), 50):
            await ws.send_text(json.dumps(
                {"type": "frames", "frames": run.frames[i:i + 50]}))
        if run.done:
            await ws.send_text(json.dumps({"type": "done", "summary": run.summary}))
            return
        while True:
            msg = await q.get()
            await ws.send_text(json.dumps(msg))
            if msg["type"] == "done":
                return
    except WebSocketDisconnect:
        pass
    finally:
        if q in run.subscribers:
            run.subscribers.remove(q)


@app.get("/api/stats")
async def stats() -> dict:
    return await asyncio.to_thread(db.visit_stats)


# ---------------- static frontend ----------------
DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str, request: Request):
        target = DIST / path
        if path and target.is_file():
            return FileResponse(target)
        # page view (not an asset): record a first-party analytics entry
        await asyncio.to_thread(
            db.log_visit, f"/{path}",
            request.headers.get("referer"), request.headers.get("user-agent"))
        return FileResponse(DIST / "index.html")
