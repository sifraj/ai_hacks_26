from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Direction = Literal["LONG", "SHORT", "NEUTRAL"]


class Signal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: str
    source_agent: Literal["momentum_analyst", "sentiment_analyst", "onchain_analyst"]
    asset: str
    direction: Direction
    confidence_score: float = Field(ge=0.0, le=1.0)
    horizon_hours: float = Field(gt=0.0)
    supporting_factors: list[str] = Field(default_factory=list)
    contradicting_factors: list[str] = Field(default_factory=list)
    raw_metrics: dict[str, float] | None = None


class SignalBatch(BaseModel):
    tick_id: str
    timestamp: str
    signals: list[Signal] = Field(default_factory=list)
