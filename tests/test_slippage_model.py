import pytest

from src.paper_trading.slippage_model import (
    calculate_slippage,
    BASE_SLIPPAGE_PCT,
    IMPACT_COEFFICIENT,
    MAX_SLIPPAGE_PCT,
)


def test_base_slippage_at_zero_size():
    assert calculate_slippage(0.0, 10_000_000.0) == pytest.approx(BASE_SLIPPAGE_PCT)


def test_slippage_scales_with_size_ratio():
    size_usd = 100_000.0
    volume = 10_000_000.0
    expected = BASE_SLIPPAGE_PCT + IMPACT_COEFFICIENT * (size_usd / volume)
    assert calculate_slippage(size_usd, volume) == pytest.approx(expected)


def test_slippage_capped_at_max():
    assert calculate_slippage(50_000_000.0, 1_000.0) == MAX_SLIPPAGE_PCT


def test_zero_volume_returns_max_slippage():
    assert calculate_slippage(1000.0, 0.0) == MAX_SLIPPAGE_PCT


def test_negative_volume_returns_max_slippage():
    assert calculate_slippage(1000.0, -500.0) == MAX_SLIPPAGE_PCT


def test_small_order_relative_to_volume_near_base():
    result = calculate_slippage(1.0, 100_000_000.0)
    assert result == pytest.approx(BASE_SLIPPAGE_PCT, rel=1e-3)
