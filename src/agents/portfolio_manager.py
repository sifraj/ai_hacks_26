from __future__ import annotations

import json
from typing import Any

from src.agents.base_agent import BaseAgent
from src.schemas.portfolio import PortfolioState
from src.schemas.regime import MarketRegime
from src.schemas.signals import SignalBatch
from src.schemas.trades import ProposedTrade

SYSTEM_PROMPT = """You are the Portfolio Manager of an automated crypto trading fund.

ROLE: Synthesize research signals and the CIO's market regime into specific trade
proposals. You balance return opportunity against portfolio construction.

INPUTS: SignalBatch from all analysts, MarketRegime from CIO, current PortfolioState.

OUTPUTS: ProposedTrade[] JSON only.

PORTFOLIO CONSTRUCTION RULES:
- Apply the CIO posture multiplier to all position sizing
- Maximum single-asset allocation: 20% of portfolio (paper value)
- Minimum trade size: $500 paper equivalent
- Do not propose trades that increase correlation when portfolio beta is already high
- Prefer signals with corroboration across multiple analysts (momentum + sentiment
  agreement outweighs single-source signals)
- Conflicting signals (one analyst bullish, another bearish on same asset):
  do not trade unless one signal confidence is >0.8 and the other <0.4
- Always provide trade_rationale citing which signals drove the decision

You propose trades. You do not approve them. Risk Manager has final say.
Your output is ProposedTrade[] JSON only."""

MAX_PROPOSED_TRADES = 5


class PortfolioManager(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="portfolio_manager",
            allowed_tools=["read_signals", "read_regime", "read_portfolio_state", "write_proposed_trades"],
        )

    async def _run_impl(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"proposed": []}

    def _build_user_message(
        self, signal_batch: SignalBatch, regime: MarketRegime, portfolio_state: PortfolioState
    ) -> str:
        payload = {
            "signal_batch": signal_batch.model_dump(),
            "market_regime": regime.model_dump(),
            "portfolio_state": portfolio_state.model_dump(),
        }
        return json.dumps(payload)

    def _parse_proposed_trades(self, raw_text: str, tick_id: str) -> list[ProposedTrade]:
        data = json.loads(raw_text)
        if not isinstance(data, list):
            raise ValueError("expected a JSON array of ProposedTrade objects")

        trades: list[ProposedTrade] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            item["tick_id"] = tick_id
            item.pop("proposal_id", None)

            try:
                trade = ProposedTrade.model_validate(item)
            except Exception as e:
                self.logger.error(
                    "portfolio_manager_trade_rejected",
                    event_type="portfolio_manager_trade_rejected",
                    payload={"error": str(e), "raw_item": item},
                )
                continue

            trades.append(trade)

        return trades[:MAX_PROPOSED_TRADES]

    async def run(
        self,
        signal_batch: SignalBatch,
        regime: MarketRegime,
        portfolio_state: PortfolioState,
    ) -> list[ProposedTrade]:
        await super().run({"tick_id": signal_batch.tick_id})

        user_message = self._build_user_message(signal_batch, regime, portfolio_state)

        try:
            raw_response = await self._call_llm(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=SYSTEM_PROMPT,
                max_tokens=2000,
            )
        except Exception as e:
            self.logger.error(
                "portfolio_manager_llm_call_failed",
                event_type="portfolio_manager_llm_call_failed",
                payload={"error": str(e)},
            )
            return []

        try:
            return self._parse_proposed_trades(raw_response, signal_batch.tick_id)
        except (json.JSONDecodeError, ValueError) as e:
            self.logger.warning(
                "portfolio_manager_parse_failed",
                event_type="portfolio_manager_parse_failed",
                payload={"error": str(e), "raw_response": raw_response},
            )
            return []


portfolio_manager = PortfolioManager()
