# next.md — Bug Backlog & Improvements

Review of 2026-06-21. Most items have since been **fixed** (✅) in the same pass.
Remaining open items are at the bottom.

---

## ✅ Fixed in this pass

### C1. Realized P&L destroyed on every sell — FIXED
Positions are now **quantity-based** (`Position.quantity` is the source of truth; `entry_price`
is average cost/unit; `size_usd` is marked to market). Sells settle proceeds at market value
and book realized P&L into a new `PortfolioState.realized_pnl_usd` and into cash.
Verified live: buy $10k → price doubles → sell → realized ≈ +$9,960, total ≈ $109,780
(previously collapsed to ~$99,880). Regression test: `test_sell_realizes_pnl_into_cash`.

### C2. Live loop never marked to market — FIXED
`paper_engine.mark_to_market()` added and called twice per tick in `run_tick` — once after
ingestion (so the decision chain sees live unrealized P&L) and once before the post-fill risk
checks (so RISK_001 drawdown / RISK_002 daily-loss can actually trigger). Regression test:
`test_marks_to_market_during_tick`.

### H1. RISK_002 trading-halt was write-only — FIXED
State manager now writes a **dated** `risk:trading_halted` flag; `risk_manager` reads it and
rejects new BUYs for the rest of the day even if daily P&L recovers (SELLs to close still
allowed). Auto-expires at the next UTC day. Tests: `test_sticky_halt_*`.

### H2. Naked sells fabricated cash — FIXED
`execute_paper_order` now raises on a SELL with no open position and caps a sell at the
position's market value. Test: `test_naked_sell_with_no_position_is_rejected`.

### M1. `MAX_LLM_CALLS_PER_TICK` unenforced — FIXED
Global per-tick `llm_budget` reset in `run_tick`, consumed by every `_call_llm`. CIO and PM
pass `critical=True` to bypass the cap so analyst spend can't starve the decision chain
(which previously reintroduced the defensive-bias bug). Tests: `test_llm_budget_*`.

### M2. "Daily" P&L never reset — FIXED
`PortfolioState` gained `daily_baseline_usd` / `daily_baseline_date`; `_update_daily_pnl`
rolls the baseline to the day's opening value each UTC day, so `daily_pnl_pct` is true daily
P&L (what RISK_002 checks).

### M3. Agent audit events didn't reach the JSONL under uvicorn — FIXED
Root cause: module-level loggers bind at import (pre-`configure`) and a structlog logger bound
that early freezes the default stdout-only config. `get_logger` now returns a `_LazyAuditLogger`
that re-resolves a fresh logger on every call, so all events route through the configured file
handler. Verified with a pre/post-configure ordering test.

### M4. Signals not persisted — FIXED (partial)
`run_tick` now persists each signal to Redis via `publish_signal` (queryable history).
Backtest→dashboard event broadcasting is intentionally **not** wired (flooding the live Signal
Feed from a 169-tick backtest is the wrong UX; the Backtesting page has its own results view).

### Cleanups — FIXED
- `numpy>=1.26.0,<2.0` pinned (kills the NumPy-2 ABI warnings from pandas-ta/numba).
- Removed the obsolete `version:` key from `docker-compose.yml`.
- On-chain payload now carries an explicit `fetched_at`; the analyst's freshness gate uses it
  instead of inferring age from the Redis TTL (falls back to TTL for old payloads).
- Schema bounds added earlier (positive sizes/prices, bounded pcts) remain in force.

---

## 🔭 Still open (deliberately deferred)

- **Unify backtest & live execution paths.** The backtester calls `paper_engine` directly and
  skips the execution-agent broadcast/queue path, so the two can drift. Worth a shared
  execution helper.
- **Persist provenance to TimescaleDB.** Signals/proposals/decisions/fills live only in
  Redis/WebSocket; the Trade Log provenance chain doesn't survive a restart and isn't queryable
  historically.
- **Full session lifecycle.** Daily P&L resets, but there's no explicit "session reset"
  (session-high re-anchor, manual halt clear) beyond the daily rollover.
- **Dead Redis keys / config.** `market_ingestor` writes `price:latest:*` / `price:live:*` that
  nothing reads (engine prices come from TimescaleDB); `coinglass/cryptopanic/glassnode` API-key
  config fields are now unused. Harmless; remove when convenient.
- **Backtest realism**: order-book depth, partial fills, and funding costs are not modelled.
