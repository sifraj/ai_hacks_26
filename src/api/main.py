from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_background_tasks: list[asyncio.Task] = []
_scheduler: Any = None


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    from src.data.redis_client import redis_client
    from src.data.timescale_client import timescale_client
    from src.harness.agent_loop import create_scheduler
    from src.harness.kill_switch import kill_switch_monitor

    await redis_client.connect()
    await timescale_client.connect()

    global _scheduler
    _scheduler = create_scheduler()
    _scheduler.start()

    _background_tasks.append(asyncio.create_task(kill_switch_monitor.run()))

    yield

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)

    for task in _background_tasks:
        task.cancel()

    await redis_client.close()
    await timescale_client.close()


app = FastAPI(title="Crypto Hedge Fund API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket connections
_connections: list[WebSocket] = []


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "services": {
            "api": "running",
            "timescaledb": "unknown",
            "redis": "unknown",
        },
    }


@app.get("/api/portfolio")
async def get_portfolio() -> dict[str, Any]:
    from src.paper_trading.paper_engine import paper_engine

    state = await paper_engine.get_portfolio_state()
    return state.model_dump()


@app.post("/api/control/kill")
async def trigger_kill_switch() -> dict[str, Any]:
    from src.harness.kill_switch import kill_switch_monitor

    kill_switch_monitor.trigger_via_api()
    return {"status": "kill_switch_triggered"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        _connections.remove(websocket)


async def broadcast(message: dict) -> None:
    dead: list[WebSocket] = []
    for ws in _connections:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.remove(ws)


class BacktestRunRequest(BaseModel):
    start_date: str
    end_date: str


# In-memory job store — fine for a single-process local dev server; not durable across restarts.
_backtest_jobs: dict[str, dict[str, Any]] = {}


@app.post("/api/backtest/run")
async def run_backtest(request: BacktestRunRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    from src.backtesting.backtest_runner import backtest_runner

    job_id = str(uuid.uuid4())
    _backtest_jobs[job_id] = {"status": "running", "result": None, "error": None}

    async def progress_callback(update: dict) -> None:
        await broadcast({"event_type": "backtest_progress", "job_id": job_id, "payload": update})

    async def _run() -> None:
        try:
            start = datetime.fromisoformat(request.start_date)
            end = datetime.fromisoformat(request.end_date)
            result = await backtest_runner.run(start, end, progress_callback=progress_callback)
            encoded_result = jsonable_encoder(result)
            _backtest_jobs[job_id] = {"status": "complete", "result": encoded_result, "error": None}
            await broadcast({"event_type": "backtest_complete", "job_id": job_id, "payload": encoded_result})
        except Exception as e:
            _backtest_jobs[job_id] = {"status": "failed", "result": None, "error": str(e)}
            await broadcast({"event_type": "backtest_failed", "job_id": job_id, "payload": {"error": str(e)}})

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "started"}


@app.get("/api/backtest/results/{job_id}")
async def get_backtest_result(job_id: str) -> dict[str, Any]:
    job = _backtest_jobs.get(job_id)
    if job is None:
        return {"status": "not_found"}
    return job
