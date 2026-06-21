from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

Posture = Literal["AGGRESSIVE", "NEUTRAL", "DEFENSIVE", "FLAT"]
RegimeType = Literal["RISK_ON", "RISK_OFF", "HIGH_VOLATILITY", "RANGING"]


class MarketRegime(BaseModel):
    tick_id: str
    timestamp: str
    regime: RegimeType
    posture: Posture
    posture_multiplier: float
    regime_rationale: str
    signal_ids_cited: list[str]

    @field_validator("posture_multiplier")
    @classmethod
    def validate_posture_multiplier(cls, v: float) -> float:
        allowed = {1.0, 0.6, 0.3, 0.0}
        if v not in allowed:
            raise ValueError(f"posture_multiplier must be one of {allowed}, got {v}")
        return v

    @field_validator("signal_ids_cited")
    @classmethod
    def validate_min_citations(cls, v: list[str]) -> list[str]:
        if len(v) < 3:
            raise ValueError("signal_ids_cited must cite at least 3 signals")
        return v
