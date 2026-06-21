from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT"]
RiskDecisionStatus = Literal["APPROVED", "RESIZED", "REJECTED"]


class ProposedTrade(BaseModel):
    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    tick_id: str
    asset: str
    side: OrderSide
    order_type: OrderType
    size_usd: float
    limit_price: float | None = None
    stop_loss_pct: float
    take_profit_pct: float | None = None
    trade_rationale: str
    signal_ids: list[str] = Field(default_factory=list)
    confidence_composite: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_limit_price_required(self) -> "ProposedTrade":
        if self.order_type == "LIMIT" and self.limit_price is None:
            raise ValueError("limit_price is required when order_type is LIMIT")
        return self


class RiskDecision(BaseModel):
    proposal_id: str
    status: RiskDecisionStatus
    approved_size_usd: float | None = None
    risk_rationale: str
    rules_checked: list[str] = Field(default_factory=list)
    rules_violated: list[str] | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> "RiskDecision":
        if self.status in ("APPROVED", "RESIZED") and self.approved_size_usd is None:
            raise ValueError("approved_size_usd is required when status is APPROVED or RESIZED")
        if self.status in ("REJECTED", "RESIZED") and not self.rules_violated:
            raise ValueError("rules_violated is required when status is REJECTED or RESIZED")
        return self


class ClearedTrade(BaseModel):
    cleared_id: str = Field(default_factory=lambda: str(uuid4()))
    proposal_id: str
    asset: str
    side: OrderSide
    order_type: OrderType
    final_size_usd: float
    limit_price: float | None = None
    stop_loss_pct: float
    compliance_checks_passed: list[str] = Field(default_factory=list)


class Fill(BaseModel):
    fill_id: str = Field(default_factory=lambda: str(uuid4()))
    cleared_id: str
    asset: str
    side: OrderSide
    filled_size_usd: float
    fill_price: float
    fee_usd: float
    timestamp: str
    paper_trade: bool = True
