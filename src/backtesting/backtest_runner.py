from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from src.agents.cio_agent import cio_agent
from src.agents.compliance_agent import compliance_agent
from src.agents.execution_agent import execution_agent
from src.agents.portfolio_manager import portfolio_manager
from src.agents.risk_manager import risk_manager
from src.agents.analysts.momentum_analyst import momentum_analyst
from src.agents.analysts.onchain_analyst import onchain_analyst
from src.agents.analysts.sentiment_analyst import sentiment_analyst
from src.backtesting.performance_metrics import PerformanceReport, compute_performance_report
from src.data.timescale_client import timescale_client
from src.harness.audit_logger import get_logger
from src.paper_trading.paper_engine import InMemoryStateStore, PaperTradingEngine
from src.schemas.signals import Signal, SignalBatch
from src.schemas.trades import Fill

logger = get_logger("backtest_runner")

ASSETS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD",
    "ADA-USD", "AVAX-USD", "DOT-USD", "POL-USD", "LINK-USD",
]

ProgressCallback = Callable[[dict], Awaitable[None]]


class HistoricalMarketDataProvider:
    """Resolves prices/volume as-of the simulated backtest clock, not live 'now'."""

    def __init__(self) -> None:
        self.prices: dict[str, float] = {}
        self.volumes: dict[str, float] = {}

    async def get_price(self, asset: str) -> float:
        if asset not in self.prices:
            raise ValueError(f"no historical price loaded for {asset} at this tick")
        return self.prices[asset]

    async def get_24h_volume(self, asset: str) -> float:
        return self.volumes.get(asset, 10_000_000.0)


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    tick_count: int
    fills: list[Fill] = field(default_factory=list)
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    performance: PerformanceReport | None = None
    fill_signal_ids: dict[str, list[str]] = field(default_factory=dict)
    signal_source_agents: dict[str, str] = field(default_factory=dict)


class BacktestRunner:
    def __init__(self) -> None:
        self.market_data = HistoricalMarketDataProvider()
        self.state_store = InMemoryStateStore()
        self.paper_engine = PaperTradingEngine(state_store=self.state_store, market_data=self.market_data)

    async def _load_historical_candles(
        self, start_date: datetime, end_date: datetime, interval: str = "1h"
    ) -> dict[str, list[dict]]:
        candles_by_asset: dict[str, list[dict]] = {}
        for asset in ASSETS:
            rows = await timescale_client.get_ohlcv(asset, start_date, end_date, interval)
            candles_by_asset[asset] = rows
        return candles_by_asset

    def _candle_at_or_before(self, candles: list[dict], ts: datetime) -> dict | None:
        candidate = None
        for row in candles:
            row_time = row["time"]
            if row_time <= ts:
                candidate = row
            else:
                break
        return candidate

    async def _generate_signals(self, tick_id: str) -> SignalBatch:
        results = []
        for analyst in (momentum_analyst, sentiment_analyst, onchain_analyst):
            try:
                results.extend(await analyst.run(tick_id))
            except Exception as e:
                logger.error(
                    "backtest_analyst_failed",
                    event_type="backtest_analyst_failed",
                    payload={"analyst": analyst.name, "error": str(e)},
                )
        return SignalBatch(
            tick_id=tick_id, timestamp=datetime.now(timezone.utc).isoformat(), signals=results
        )

    async def run(
        self,
        start_date: datetime,
        end_date: datetime,
        tick_interval: timedelta = timedelta(hours=1),
        progress_callback: ProgressCallback | None = None,
    ) -> BacktestResult:
        candles_by_asset = await self._load_historical_candles(start_date, end_date, "1h")

        all_fills: list[Fill] = []
        fill_signal_ids: dict[str, list[str]] = {}
        signal_source_agents: dict[str, str] = {}
        equity_curve: list[tuple[datetime, float]] = []

        current_time = start_date
        tick_count = 0

        while current_time <= end_date:
            tick_id = str(uuid.uuid4())

            # Advance the simulated market clock — set "as of now" prices for this tick.
            for asset, candles in candles_by_asset.items():
                bar = self._candle_at_or_before(candles, current_time)
                if bar is not None:
                    self.market_data.prices[asset] = bar["close"]
                    self.market_data.volumes[asset] = bar["volume"]

            if not self.market_data.prices:
                current_time += tick_interval
                continue

            signal_batch = await self._generate_signals(tick_id)
            for s in signal_batch.signals:
                signal_source_agents[s.signal_id] = s.source_agent

            regime = await cio_agent.run(signal_batch)
            portfolio_state = await self.paper_engine.get_portfolio_state()
            proposed = await portfolio_manager.run(signal_batch, regime, portfolio_state)
            approved = await risk_manager.evaluate(proposed, portfolio_state)
            cleared = await compliance_agent.check_all(approved, proposed)

            proposed_by_id = {p.proposal_id: p for p in proposed}
            for cleared_trade in cleared:
                trade = proposed_by_id.get(cleared_trade.proposal_id)
                if trade:
                    fill_signal_ids[cleared_trade.cleared_id] = trade.signal_ids

            fills: list[Fill] = []
            for cleared_trade in cleared:
                fill = await self.paper_engine.execute_paper_order(cleared_trade)
                fills.append(fill)
            all_fills.extend(fills)

            updated_state = await self.paper_engine.update_positions_with_prices(self.market_data.prices)
            equity_curve.append((current_time, updated_state.total_value_usd))

            tick_count += 1
            if progress_callback is not None:
                await progress_callback(
                    {
                        "tick_id": tick_id,
                        "timestamp": current_time.isoformat(),
                        "tick_count": tick_count,
                        "total_value_usd": updated_state.total_value_usd,
                    }
                )

            current_time += tick_interval

        performance = compute_performance_report(
            fills=all_fills,
            fill_signal_ids=fill_signal_ids,
            signal_source_agents=signal_source_agents,
            equity_curve=equity_curve,
            initial_cash_usd=100_000.0,
        )

        return BacktestResult(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            tick_count=tick_count,
            fills=all_fills,
            equity_curve=[(ts.isoformat(), value) for ts, value in equity_curve],
            performance=performance,
            fill_signal_ids=fill_signal_ids,
            signal_source_agents=signal_source_agents,
        )


backtest_runner = BacktestRunner()
