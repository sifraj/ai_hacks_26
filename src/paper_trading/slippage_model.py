BASE_SLIPPAGE_PCT = 0.001   # 0.1%
IMPACT_COEFFICIENT = 0.005  # 0.5%
MAX_SLIPPAGE_PCT = 0.02     # 2% cap


def calculate_slippage(size_usd: float, asset_24h_volume_usd: float) -> float:
    if asset_24h_volume_usd <= 0:
        return MAX_SLIPPAGE_PCT
    slippage = BASE_SLIPPAGE_PCT + IMPACT_COEFFICIENT * (size_usd / asset_24h_volume_usd)
    return min(slippage, MAX_SLIPPAGE_PCT)
