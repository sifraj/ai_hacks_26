from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import src.api.main as main_module
from src.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_run_backtest_returns_job_id_immediately(client, monkeypatch):
    fake_backtest_runner = AsyncMock()
    fake_backtest_runner.run = AsyncMock(return_value="ignored — backgrounded")

    import src.backtesting.backtest_runner as backtest_runner_module
    monkeypatch.setattr(backtest_runner_module, "backtest_runner", fake_backtest_runner)

    response = client.post(
        "/api/backtest/run",
        json={"start_date": "2026-01-01T00:00:00+00:00", "end_date": "2026-01-02T00:00:00+00:00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "started"


def test_get_unknown_job_returns_not_found(client):
    response = client.get("/api/backtest/results/does-not-exist")
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


def test_job_completes_and_result_is_fetchable(client, monkeypatch):
    from dataclasses import dataclass

    @dataclass
    class FakeResult:
        tick_count: int
        total_value_usd: float

    fake_backtest_runner = AsyncMock()

    async def fake_run(start, end, progress_callback=None):
        if progress_callback:
            await progress_callback({"tick_count": 1})
        return FakeResult(tick_count=1, total_value_usd=101_000.0)

    fake_backtest_runner.run = fake_run

    import src.backtesting.backtest_runner as backtest_runner_module
    monkeypatch.setattr(backtest_runner_module, "backtest_runner", fake_backtest_runner)

    response = client.post(
        "/api/backtest/run",
        json={"start_date": "2026-01-01T00:00:00+00:00", "end_date": "2026-01-02T00:00:00+00:00"},
    )
    job_id = response.json()["job_id"]

    result_response = client.get(f"/api/backtest/results/{job_id}")
    body = result_response.json()
    assert body["status"] == "complete"
    assert body["result"]["tick_count"] == 1


def test_job_failure_is_recorded(client, monkeypatch):
    fake_backtest_runner = AsyncMock()

    async def fake_run(start, end, progress_callback=None):
        raise RuntimeError("no historical data")

    fake_backtest_runner.run = fake_run

    import src.backtesting.backtest_runner as backtest_runner_module
    monkeypatch.setattr(backtest_runner_module, "backtest_runner", fake_backtest_runner)

    response = client.post(
        "/api/backtest/run",
        json={"start_date": "2026-01-01T00:00:00+00:00", "end_date": "2026-01-02T00:00:00+00:00"},
    )
    job_id = response.json()["job_id"]

    result_response = client.get(f"/api/backtest/results/{job_id}")
    body = result_response.json()
    assert body["status"] == "failed"
    assert "no historical data" in body["error"]
