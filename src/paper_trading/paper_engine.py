from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from src.data.redis_client import redis_client
from src.data.timescale_client import timescale_client
from src.harness.audit_logger import get_logger
from src.paper_trading.slippage_model import calculate_slippage
from src.schemas.portfolio import PortfolioState, Position
from src.schemas.trades import ClearedTrade, Fill

logger = get_logger("paper_engine")

INITIAL_CASH_USD = 100_000.0
TAKER_FEE_PCT = 0.006  # 0.6%
DEFAULT_24H_VOLUME_USD = 10_000_000.0  # fallback when no historical volume data


class LiveMarketDataProvider:
    """Default market data source: latest price/volume from TimescaleDB ("now")."""

    async def get_price(self, asset: str) -> float:
        price = await timescale_client.get_latest_price(asset)
        if price is None:
            raise ValueError(f"no market price available for {asset}")
        return price

    async def get_24h_volume(self, asset: str) -> float:
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=1)
            rows = await timescale_client.get_ohlcv(asset, start, end, "1d")
            if rows:
                return float(rows[-1]["volume"]) or DEFAULT_24H_VOLUME_USD
        except Exception:
            pass
        return DEFAULT_24H_VOLUME_USD


class InMemoryStateStore:
    """Isolated, non-persistent state store — used by backtests so they never
    touch the live Redis-backed portfolio state."""

    def __init__(self) -> None:
        self._state: dict | None = None

    async def get_portfolio_state(self) -> dict | None:
        return self._state

    async def set_portfolio_state(self, state: dict) -> None:
        self._state = state


class PaperTradingEngine:
    def __init__(self, state_store: Any = None, market_data: Any = None) -> None:
        self._state_store = state_store or redis_client
        self._market_data = market_data or LiveMarketDataProvider()

    def _initial_state(self) -> PortfolioState:
        now = datetime.now(timezone.utc).isoformat()
        return PortfolioState(
            timestamp=now,
            total_value_usd=INITIAL_CASH_USD,
            cash_usd=INITIAL_CASH_USD,
            positions=[],
            session_high_usd=INITIAL_CASH_USD,
            daily_pnl_usd=0.0,
            daily_pnl_pct=0.0,
            drawdown_from_session_high_pct=0.0,
            kill_switch=False,
        )

    async def get_portfolio_state(self) -> PortfolioState:
        raw = await self._state_store.get_portfolio_state()
        if raw is None:
            state = self._initial_state()
            await self._save_state(state)
            return state
        return PortfolioState.model_validate(raw)

    async def _save_state(self, state: PortfolioState) -> None:
        await self._state_store.set_portfolio_state(state.model_dump())

    async def _get_24h_volume(self, asset: str) -> float:
        return await self._market_data.get_24h_volume(asset)

    async def _get_market_price(self, asset: str) -> float:
        return await self._market_data.get_price(asset)

    def _recalculate_totals(self, state: PortfolioState) -> PortfolioState:
        positions_value = sum(p.size_usd + p.unrealized_pnl_usd for p in state.positions)
        total_value = state.cash_usd + positions_value
        state.total_value_usd = total_value
        state.session_high_usd = max(state.session_high_usd, total_value)
        state.drawdown_from_session_high_pct = (
            (state.session_high_usd - total_value) / state.session_high_usd
            if state.session_high_usd > 0
            else 0.0
        )
        return state

    async def execute_paper_order(self, cleared_trade: ClearedTrade) -> Fill:
        assert cleared_trade.final_size_usd > 0, "final_size_usd must be positive"

        await asyncio.sleep(random.uniform(0.1, 0.5))

        market_price = await self._get_market_price(cleared_trade.asset)
        volume_24h = await self._get_24h_volume(cleared_trade.asset)
        slippage_pct = calculate_slippage(cleared_trade.final_size_usd, volume_24h)

        if cleared_trade.side == "BUY":
            fill_price = market_price * (1 + slippage_pct)
        else:
            fill_price = market_price * (1 - slippage_pct)

        fee_usd = cleared_trade.final_size_usd * TAKER_FEE_PCT

        fill = Fill(
            cleared_id=cleared_trade.cleared_id,
            asset=cleared_trade.asset,
            side=cleared_trade.side,
            filled_size_usd=cleared_trade.final_size_usd,
            fill_price=fill_price,
            fee_usd=fee_usd,
            timestamp=datetime.now(timezone.utc).isoformat(),
            paper_trade=True,
        )

        await self._apply_fill(fill, cleared_trade.stop_loss_pct)

        logger.info(
            "paper_order_filled",
            event_type="paper_order_filled",
            payload=fill.model_dump(),
        )
        return fill

    async def _apply_fill(self, fill: Fill, stop_loss_pct: float) -> PortfolioState:
        state = await self.get_portfolio_state()
        positions_by_asset = {p.asset: p for p in state.positions}
        existing = positions_by_asset.get(fill.asset)

        if fill.side == "BUY":
            state.cash_usd -= fill.filled_size_usd + fill.fee_usd
            if existing is None:
                stop_loss_price = fill.fill_price * (1 - stop_loss_pct)
                new_position = Position(
                    asset=fill.asset,
                    size_usd=fill.filled_size_usd,
                    entry_price=fill.fill_price,
                    current_price=fill.fill_price,
                    unrealized_pnl_usd=0.0,
                    unrealized_pnl_pct=0.0,
                    stop_loss_price=stop_loss_price,
                )
                state.positions.append(new_position)
            else:
                total_size = existing.size_usd + fill.filled_size_usd
                existing.entry_price = (
                    (existing.entry_price * existing.size_usd) + (fill.fill_price * fill.filled_size_usd)
                ) / total_size
                existing.size_usd = total_size
                existing.current_price = fill.fill_price
                existing.stop_loss_price = existing.entry_price * (1 - stop_loss_pct)
        else:  # SELL — reduce or close position
            state.cash_usd += fill.filled_size_usd - fill.fee_usd
            if existing is not None:
                existing.size_usd -= fill.filled_size_usd
                existing.current_price = fill.fill_price
                if existing.size_usd <= 0:
                    state.positions = [p for p in state.positions if p.asset != fill.asset]

        state = self._recompute_unrealized_pnl(state)
        state = self._recalculate_totals(state)
        state.timestamp = datetime.now(timezone.utc).isoformat()
        await self._save_state(state)
        return state

    def _recompute_unrealized_pnl(self, state: PortfolioState) -> PortfolioState:
        for position in state.positions:
            position.unrealized_pnl_usd = (
                (position.current_price - position.entry_price) / position.entry_price
            ) * position.size_usd
            position.unrealized_pnl_pct = (
                (position.current_price - position.entry_price) / position.entry_price
                if position.entry_price > 0
                else 0.0
            )
        return state

    async def update_positions_with_prices(self, prices: dict[str, float]) -> PortfolioState:
        state = await self.get_portfolio_state()
        for position in state.positions:
            if position.asset in prices:
                position.current_price = prices[position.asset]

        state = self._recompute_unrealized_pnl(state)
        state = self._recalculate_totals(state)

        cash_baseline = INITIAL_CASH_USD
        state.daily_pnl_usd = state.total_value_usd - cash_baseline
        state.daily_pnl_pct = (
            state.daily_pnl_usd / cash_baseline if cash_baseline > 0 else 0.0
        )
        state.timestamp = datetime.now(timezone.utc).isoformat()
        await self._save_state(state)
        return state

    async def close_all_positions(self) -> list[Fill]:
        state = await self.get_portfolio_state()
        fills: list[Fill] = []
        for position in list(state.positions):
            cleared_trade = ClearedTrade(
                proposal_id="kill_switch_close",
                asset=position.asset,
                side="SELL",
                order_type="MARKET",
                final_size_usd=position.size_usd,
                stop_loss_pct=0.0,
                compliance_checks_passed=["KILL_SWITCH_FORCE_CLOSE"],
            )
            fill = await self.execute_paper_order(cleared_trade)
            fills.append(fill)

        logger.info(
            "all_positions_closed",
            event_type="all_positions_closed",
            payload={"fill_count": len(fills)},
        )
        return fills


paper_engine = PaperTradingEngine()


if __name__ == "__main__":
    import asyncio as _asyncio

    async def _demo() -> None:
        await redis_client.connect()
        await timescale_client.connect()

        # Reset to a clean initial state for the demo
        await redis_client.client.delete("portfolio:state")
        state = await paper_engine.get_portfolio_state()
        print("Initial state:")
        print(state.model_dump_json(indent=2))

        demo_assets = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "LINK-USD"]
        demo_prices = {
            "BTC-USD": 65_000.0,
            "ETH-USD": 3_500.0,
            "SOL-USD": 150.0,
            "ADA-USD": 0.45,
            "LINK-USD": 14.0,
        }

        # Seed fake market prices directly in TimescaleDB so _get_market_price works
        now = datetime.now(timezone.utc)
        for asset, price in demo_prices.items():
            await timescale_client.insert_ohlcv(
                asset=asset, interval="5m", time=now,
                open=price, high=price, low=price, close=price, volume=5_000_000.0,
            )

        for asset in demo_assets:
            cleared = ClearedTrade(
                proposal_id=f"demo-{asset}",
                asset=asset,
                side="BUY",
                order_type="MARKET",
                final_size_usd=2_000.0,
                stop_loss_pct=0.02,
                compliance_checks_passed=["RULE_DEMO"],
            )
            fill = await paper_engine.execute_paper_order(cleared)
            print(f"Filled {asset}: {fill.model_dump_json()}")

        state = await paper_engine.get_portfolio_state()
        print("\nPortfolio state after 5 buys:")
        print(state.model_dump_json(indent=2))

        # Simulate price changes
        new_prices = {
            "BTC-USD": 67_000.0,
            "ETH-USD": 3_400.0,
            "SOL-USD": 160.0,
            "ADA-USD": 0.42,
            "LINK-USD": 15.0,
        }
        state = await paper_engine.update_positions_with_prices(new_prices)
        print("\nPortfolio state after price changes:")
        print(state.model_dump_json(indent=2))

        await redis_client.close()
        await timescale_client.close()

    _asyncio.run(_demo())
