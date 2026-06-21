# CLAUDE.md — Claude Code Instructions
## Crypto Hedge Fund Agent Platform

This file is the authoritative guide for Claude Code sessions on this project.
Always read SPEC.md before starting any implementation session.

---

## Project Context

This is a multi-agent autonomous crypto trading platform. The architecture,
schemas, agent personas, and risk rules are defined in SPEC.md. Do not deviate
from them without explicit user instruction.

**Current mode:** Paper trading only. No real money, no real orders.
**Exchange:** Coinbase Advanced (paper/preview endpoints only)
**LLM for agents:** claude-sonnet-4-6 via Anthropic Python SDK

---

## Ground Rules

1. **Never hardcode API keys or secrets.** Always use `os.getenv()` or Pydantic Settings.
2. **Never relax risk rules.** Hard limits in SPEC.md §6 are implemented as deterministic
   Python code, never as LLM calls. If asked to make risk rules configurable, add them
   to config but keep enforcement in code.
3. **Schema fidelity.** All Pydantic models must match SPEC.md §5 exactly. 
   If a schema needs changing, update SPEC.md first.
4. **Structured logging everywhere.** Every agent action, LLM call, tool execution,
   and error must emit a structured log event via `audit_logger.py`.
5. **Paper trading flag.** Every order placement must assert `paper_trade=True` 
   before submission.
6. **Tool scoping.** Each agent class must only import and use tools listed in 
   SPEC.md §2.4 for that agent. Enforce at the harness level.

---

## Phase Prompts

Use these prompts to start each Claude Code session. Copy-paste the relevant phase.

---

### Phase 1 — Foundation

```
We are implementing Phase 1 (Foundation) of the crypto hedge fund platform.
Read SPEC.md for full context.

Tasks for this session:
1. Create docker-compose.yml with TimescaleDB (timescale/timescaledb:latest-pg15) 
   and Redis (redis:7-alpine) services. Expose TimescaleDB on 5432, Redis on 6379.
   Add health checks for both.

2. Create .env.example with all required environment variables:
   ANTHROPIC_API_KEY, COINBASE_API_KEY, COINBASE_API_SECRET,
   CRYPTOPANIC_API_KEY, COINGLASS_API_KEY, GLASSNODE_API_KEY,
   DATABASE_URL (TimescaleDB connection string), REDIS_URL,
   PAPER_TRADING=true, TICK_INTERVAL_SECONDS=300,
   LOG_LEVEL=INFO, LOG_DIR=./logs

3. Create src/config.py using Pydantic BaseSettings. 
   All fields typed, all secrets loaded from env.

4. Create src/harness/audit_logger.py using structlog.
   Every log event must include: timestamp, tick_id, agent_name, event_type, payload.
   Output to both stdout (pretty) and ./logs/audit_{date}.jsonl (JSON lines).

5. Create src/api/main.py — FastAPI app skeleton with:
   - GET /health → returns system status
   - GET /api/portfolio → returns current portfolio state (stub for now)
   - WebSocket /ws → broadcast endpoint (stub)
   - CORS enabled for localhost:5173 (Vite dev server)

Verify each component works before moving on. Add a scripts/setup.sh that:
- Copies .env.example to .env if .env doesn't exist
- Runs docker-compose up -d
- Runs pip install -r requirements.txt
```

---

### Phase 2 — Data Pipeline

```
We are implementing Phase 2 (Data Pipeline). Read SPEC.md §4 for data sources.

Prerequisites: Phase 1 complete. Docker services running. .env populated.

Tasks:
1. Create src/data/timescale_client.py
   - Async connection pool using asyncpg
   - Methods: insert_ohlcv(), get_ohlcv(asset, start, end, interval), 
     get_latest_price(asset)
   - Create TimescaleDB hypertable migration in src/data/migrations/001_ohlcv.sql
     Table: ohlcv (time TIMESTAMPTZ, asset TEXT, open FLOAT8, high FLOAT8, 
     low FLOAT8, close FLOAT8, volume FLOAT8)

2. Create src/data/redis_client.py
   - Async Redis client using aioredis
   - Methods: set_portfolio_state(), get_portfolio_state(),
     publish_signal(), get_latest_signals(asset=None),
     set_agent_status(), get_all_agent_statuses()

3. Create src/ingestors/market_ingestor.py
   - Use ccxt.async_support.coinbase for OHLCV
   - Assets: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT, 
     ADA/USDT, AVAX/USDT, DOT/USDT, MATIC/USDT, LINK/USDT
   - Fetch 5m, 1h, 1d candles
   - Store in TimescaleDB
   - Publish latest prices to Redis
   - WebSocket subscription for live ticker

4. Create src/ingestors/sentiment_ingestor.py
   - NewsAPI.org: GET https://newsapi.org/v2/everything
     Params: q="bitcoin OR ethereum OR crypto", language="en", sortBy="publishedAt",
     pageSize=20, apiKey=NEWSAPI_KEY
   - Run one batched query covering all assets (don't query per-asset — preserve free tier quota)
   - Parse response: extract article.title + article.description for each result
   - Map articles to assets by keyword matching in title/description
     (e.g. "bitcoin" or "BTC" → BTC-USD, "ethereum" or "ETH" → ETH-USD, etc.)
   - Structure into SentimentRawData dataclass per asset:
     {asset, headlines: list[str], sources: list[str], published_at: list[str]}
   - Store in Redis with 15min TTL
   - Rate limit guard: track last fetch timestamp in Redis, skip if < 14 minutes ago

5. Create src/ingestors/onchain_ingestor.py
   - CoinGlass API: funding rates, open interest, liquidations
   - Structure into OnChainRawData dataclass per asset
   - Store in Redis with 30min TTL

Each ingestor: add error handling, retry with exponential backoff (max 3 retries),
and emit structured log on success/failure.
```

---

### Phase 3 — Paper Trading Engine

```
We are implementing Phase 3 (Paper Trading Engine). Read SPEC.md §7.1 and §6.

Prerequisites: Phases 1-2 complete. Schemas from SPEC.md §5 implemented as Pydantic
models in src/schemas/.

Tasks:
1. Create ALL Pydantic models from SPEC.md §5 in:
   src/schemas/signals.py — Signal, SignalBatch
   src/schemas/regime.py — MarketRegime
   src/schemas/trades.py — ProposedTrade, RiskDecision, ClearedTrade, Fill
   src/schemas/portfolio.py — Position, PortfolioState
   Match schemas EXACTLY as specified. Add validators where appropriate.

2. Create src/paper_trading/slippage_model.py
   - calculate_slippage(size_usd, asset_24h_volume_usd) → float (slippage %)
   - Model: 0.1% base + 0.5% * (size_usd / asset_24h_volume_usd)
   - Cap at 2% slippage

3. Create src/paper_trading/paper_engine.py
   - Maintains paper PortfolioState in Redis
   - Initial state: $100,000 paper cash, no positions
   - Methods:
     execute_paper_order(cleared_trade: ClearedTrade) → Fill
     get_portfolio_state() → PortfolioState
     update_positions_with_prices(prices: dict[str, float]) → PortfolioState
     close_all_positions() → list[Fill]  # For kill switch
   - Simulate fill: apply slippage, deduct 0.6% fee, random latency 100-500ms
   - Update position or create new one after fill
   - Recalculate unrealized P&L, drawdown, daily P&L after every update

4. Create src/harness/kill_switch.py
   - KillSwitchMonitor class that runs as background task
   - Checks three sources every 10 seconds:
     a. ./KILL_SWITCH file exists on disk
     b. portfolio_state.kill_switch == True in Redis
     c. POST /api/control/kill received (set via API)
   - On activation: set kill_switch flag in Redis, call paper_engine.close_all_positions()
   - Log KILL_SWITCH_ACTIVATED event with timestamp and trigger source
   - Once activated, cannot be deactivated without manual Redis clear + file deletion

5. Create src/agents/state_manager.py
   - Runs after each tick's fills are processed
   - Pulls fills from Redis queue
   - Updates PortfolioState via paper_engine
   - Checks hard risk rules RISK_001 and RISK_002 (drawdown and daily loss)
   - Activates kill switch if breached
   - Publishes updated state to Redis and via WebSocket

Test paper_engine.py standalone with a __main__ block that:
- Creates initial state
- Simulates 5 buy orders across different assets
- Prints portfolio state
- Simulates price changes
- Prints updated unrealized P&L
```

---

### Phase 4 — Agent Harness

```
We are implementing Phase 4 (Agent Harness). Read SPEC.md §2.

Tasks:
1. Create src/agents/base_agent.py
   Abstract base class for all agents:
   - __init__(name, allowed_tools, logger)
   - abstract async run(context: dict) → dict
   - _call_llm(messages, system_prompt, max_tokens=1000) → str
     Uses Anthropic Python SDK, model=claude-sonnet-4-6
     Logs: agent_name, prompt_tokens, completion_tokens, latency_ms
   - _use_tool(tool_name, **kwargs) — checks tool is in allowed_tools, raises if not
   - Emits structured log on every run() start and end with latency

2. Create src/harness/tool_registry.py
   - Define all tools as Python callables
   - ToolRegistry class: register(name, fn), get(name) → callable
   - Enforce per-agent allowed_tools at call time (raise ToolAccessDeniedError if violated)
   - Log every tool invocation

3. Create src/harness/agent_loop.py
   Main tick orchestrator:
   
   async def run_tick(tick_id: str):
     # Phase 1: Parallel ingestion
     await asyncio.gather(market_ingestor.run(), sentiment_ingestor.run(), onchain_ingestor.run())
     
     # Phase 2: Parallel analysis  
     signals = await asyncio.gather(
       momentum_analyst.run(tick_id),
       sentiment_analyst.run(tick_id),
       onchain_analyst.run(tick_id)
     )
     signal_batch = SignalBatch(tick_id=tick_id, signals=flatten(signals))
     
     # Phase 3: Sequential decision chain
     regime = await cio_agent.run(signal_batch)
     portfolio_state = await state_manager.get_state()
     proposed = await portfolio_manager.run(signal_batch, regime, portfolio_state)
     approved = await risk_manager.run(proposed, portfolio_state)
     cleared = await compliance_agent.run(approved)
     fills = await execution_agent.run(cleared)
     
     # Phase 4: State update
     await state_manager.process_fills(fills)
     await audit_logger.log_tick_summary(tick_id, signal_batch, regime, proposed, approved, cleared, fills)
     await websocket_broadcaster.broadcast_tick_update()

   - APScheduler job calls run_tick() every TICK_INTERVAL_SECONDS
   - Catches and logs all exceptions without crashing the loop
   - Skips tick if kill_switch is active (log reason)
   - Tracks tick latency, logs warning if tick > 60 seconds
```

---

### Phase 5 — Research Agents

```
We are implementing Phase 5 (Research Agents). Read SPEC.md §3 for system prompts.

Tasks:
1. src/agents/analysts/momentum_analyst.py — NO LLM
   Computes technical indicators from OHLCV data:
   - RSI(14) on 1h candles
   - MACD(12,26,9) on 1h candles  
   - Bollinger Bands(20,2) on 1h candles
   - Volume ratio (current vs 20-period average)
   - 24h price change %
   
   Signal generation rules (deterministic):
   - RSI < 30 AND price at lower BB → LONG signal, confidence = (30-RSI)/30 * 0.8
   - RSI > 70 AND price at upper BB → SHORT signal, confidence = (RSI-70)/30 * 0.8
   - MACD crossover → LONG/SHORT signal, confidence 0.5
   - Volume > 2x average AND price up → add 0.1 to confidence
   - Cap confidence at 0.85
   Use pandas-ta or ta-lib for indicator computation.

2. src/agents/analysts/sentiment_analyst.py — LLM-powered
   - Fetches SentimentRawData from Redis
   - For each asset with news data, calls Claude with system prompt from SPEC.md §3.2
   - Parses JSON response into Signal[] (validate with Pydantic)
   - Handles: empty response, invalid JSON, schema mismatch
   - Retries once on parse failure with "your last response was invalid JSON" message
   - Rate limit: max 10 LLM calls per tick (batch assets together if needed)

3. src/agents/analysts/onchain_analyst.py — LLM-powered
   - Fetches OnChainRawData from Redis
   - Calls Claude with system prompt from SPEC.md §3.3
   - Same validation + retry pattern as sentiment analyst
   - Only runs if onchain data freshness < 45 minutes (else skip with log)

For all analysts: validate every Signal against Signal Pydantic schema before emitting.
Reject and log any signal that fails validation rather than crashing.
```

---

### Phase 6 — Decision Agents

```
We are implementing Phase 6 (Decision Agents). Read SPEC.md §3 and §6 carefully.

Tasks:
1. src/agents/risk_manager.py — DETERMINISTIC, NO LLM for enforcement
   Implement all hard rules from SPEC.md §6 as Python code.
   
   async def evaluate(proposed: list[ProposedTrade], state: PortfolioState) → list[RiskDecision]:
     decisions = []
     for trade in proposed:
       decision = _evaluate_single(trade, state)
       decisions.append(decision)
     return decisions
   
   _evaluate_single must check rules in this order:
   RISK_006 (kill switch) → RISK_001 (drawdown) → RISK_002 (daily loss) →
   RISK_005 (long exposure) → RISK_004 (asset allocation) → RISK_003 (position loss)
   First violated hard rule → REJECT with rule ID cited.
   
   Position sizing: apply formula from SPEC.md §6 if trade passes all hard rules.
   
   IMPORTANT: Do not use LLM for any enforcement decision. 
   LLM may only be used optionally for generating human-readable risk_rationale 
   AFTER the decision is already made by code.

2. src/agents/compliance_agent.py — DETERMINISTIC, NO LLM
   Implement RULE_001 through RULE_006 from SPEC.md §3.6 as code.
   Check against Redis state and live market data.
   Return ClearedTrade[] — only trades that pass all compliance checks.

3. src/agents/cio_agent.py — LLM-powered
   System prompt: exact text from SPEC.md §3.1
   Input: SignalBatch serialized to JSON
   Output: parse MarketRegime from response, validate with Pydantic
   Fallback: if LLM call fails or response invalid → default to RANGING/DEFENSIVE

4. src/agents/portfolio_manager.py — LLM-powered
   System prompt: exact text from SPEC.md §3.4
   Input: SignalBatch + MarketRegime + PortfolioState (serialized JSON)
   Output: parse ProposedTrade[] from response, validate each with Pydantic
   Fallback: if LLM fails → return empty list (no trades this tick)
   Cap: max 5 proposed trades per tick

5. src/agents/execution_agent.py — DETERMINISTIC
   For each ClearedTrade:
   - Assert paper_trade=True (raise if not set)
   - Call paper_engine.execute_paper_order(trade)
   - Get Fill back
   - Push Fill to Redis fills queue
   - Log fill with full provenance chain (cleared_id → proposal_id → signal_ids)
```

---

### Phase 7 — Backtesting

```
We are implementing Phase 7 (Backtesting). Read SPEC.md §8.

Tasks:
1. src/backtesting/backtest_runner.py
   - Loads historical OHLCV from TimescaleDB for date range
   - Replays ticks chronologically using historical data (no live ingestion)
   - Runs same agent pipeline as live (analysts → CIO → PM → Risk → Compliance → Execution)
   - Uses paper_engine with fresh state for each backtest run
   - Returns BacktestResult dataclass

2. src/backtesting/performance_metrics.py
   Calculate all metrics from SPEC.md §8.2:
   - total_return_pct, sharpe_ratio, sortino_ratio, max_drawdown_pct,
     max_drawdown_duration_days, win_rate, avg_win_pct, avg_loss_pct,
     calmar_ratio, total_trades, avg_hold_hours
   - Per-asset breakdown
   - Per-analyst signal accuracy (did signals lead to profitable trades?)

3. src/backtesting/walk_forward.py
   - Splits date range into train/test windows
   - Default: 6-month train, 2-month test, 1-month step
   - Runs backtest on each window
   - Returns aggregated out-of-sample results only

4. Wire into FastAPI: POST /api/backtest/run {start_date, end_date}
   Returns BacktestResult as JSON. Run in background task, stream progress via WebSocket.
```

---

### Phase 8 — Dashboard

```
We are implementing Phase 8 (React Dashboard). Read SPEC.md §9.

Setup: Vite + React 18 + TypeScript + Tailwind CSS + Recharts + React Query + Zustand
Run: cd dashboard && npm create vite@latest . -- --template react-ts && npm install

Color scheme: Dark theme. Background #0f1117, cards #1a1d27, 
accent green #00d084 (profit), red #ff4757 (loss), blue #3b82f6 (neutral).

Pages to implement:

1. Overview (/) 
   - Header: total portfolio value (large), daily P&L with color, drawdown %
   - Kill switch button: top-right, red, requires "Type CONFIRM to proceed" modal
   - Agent status bar: colored dots for each agent (green=ok, yellow=slow, red=error)
   - Positions table: asset | size | entry | current | unrealized P&L | stop loss
   - Updates live via WebSocket

2. Signal Feed (/signals)
   - Live stream of Signal cards as they arrive each tick
   - Card shows: asset, direction badge (LONG=green/SHORT=red/NEUTRAL=gray), 
     confidence bar, analyst source, horizon, supporting/contradicting factors
   - Filter bar: asset dropdown, analyst filter, min confidence slider
   - Auto-scroll to latest, pause on hover

3. Trade Log (/trades)
   - Table: timestamp | asset | side | size | status | P&L
   - Status badges: PROPOSED → APPROVED/REJECTED → FILLED
   - Expandable row showing full provenance:
     Signal IDs → PM rationale → Risk decision + rules checked → Fill details
   - Filter by status, asset, date range
   - Export to CSV button

4. Backtesting (/backtest)
   - Date range picker (start/end)
   - Run Backtest button → progress bar via WebSocket
   - Results: metrics cards (return, Sharpe, max drawdown, win rate, trade count)
   - Equity curve chart (Recharts LineChart)
   - Drawdown chart
   - Per-asset performance table

5. Agent Monitor (/agents)
   - One card per agent: name, last run timestamp, last tick latency, 
     error count, current status
   - Current regime display (CIO output): large badge RISK_ON/RISK_OFF/etc + rationale
   - Live agent activity log (scrolling, most recent 100 events)

WebSocket hook: src/hooks/useWebSocket.ts
- Connects to ws://localhost:8000/ws
- Reconnects automatically on disconnect
- Dispatches events to Zustand store by event_type
```

---

## Common Patterns

### LLM Agent Call Pattern
```python
async def _call_claude(self, system: str, user_content: str) -> str:
    start = time.monotonic()
    try:
        response = await self.anthropic.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=system,
            messages=[{"role": "user", "content": user_content}]
        )
        latency_ms = (time.monotonic() - start) * 1000
        self.logger.info("llm_call_success", 
            agent=self.name,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms)
        return response.content[0].text
    except Exception as e:
        self.logger.error("llm_call_failed", agent=self.name, error=str(e))
        raise
```

### JSON Parse with Retry
```python
async def _parse_llm_json(self, raw: str, schema: type[BaseModel]) -> BaseModel:
    try:
        return schema.model_validate_json(raw.strip())
    except (ValidationError, JSONDecodeError) as e:
        self.logger.warning("json_parse_failed", agent=self.name, error=str(e))
        # Retry with correction prompt
        corrected = await self._call_claude(
            system=self.system_prompt,
            user_content=f"Your last response failed validation: {e}\n"
                        f"Return ONLY valid JSON matching the schema. No other text.\n"
                        f"Your response was: {raw}"
        )
        return schema.model_validate_json(corrected.strip())
```

### Risk Rule Check Pattern
```python
def _check_hard_rules(self, trade: ProposedTrade, state: PortfolioState) -> RiskDecision:
    # RISK_006: Kill switch
    if state.kill_switch:
        return RiskDecision(proposal_id=trade.proposal_id, status="REJECTED",
            risk_rationale="Kill switch is active", rules_checked=["RISK_006"],
            rules_violated=["RISK_006"])
    
    # RISK_001: Drawdown
    if state.drawdown_from_session_high_pct >= 0.05:
        return RiskDecision(proposal_id=trade.proposal_id, status="REJECTED",
            risk_rationale=f"Session drawdown {state.drawdown_from_session_high_pct:.1%} exceeds 5% limit",
            rules_checked=["RISK_006", "RISK_001"], rules_violated=["RISK_001"])
    
    # ... continue through all rules
```

---

## Environment Variables Reference

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Coinbase Advanced
COINBASE_API_KEY=...
COINBASE_API_SECRET=...

# Data Sources  
CRYPTOPANIC_API_KEY=...
COINGLASS_API_KEY=...
GLASSNODE_API_KEY=...

# Infrastructure
DATABASE_URL=postgresql://postgres:password@localhost:5432/hedgefund
REDIS_URL=redis://localhost:6379/0

# System Config
PAPER_TRADING=true          # NEVER set to false until fully production-ready
TICK_INTERVAL_SECONDS=300   # 5 minutes
LOG_LEVEL=INFO
LOG_DIR=./logs
MAX_LLM_CALLS_PER_TICK=15  # Cost control
```

---

## Cost Estimation (per tick, at default config)

| Agent | Avg tokens in | Avg tokens out | Calls/tick |
|---|---|---|---|
| Sentiment Analyst | ~2000 | ~500 | 1–3 |
| On-Chain Analyst | ~1500 | ~500 | 1 |
| CIO | ~3000 | ~300 | 1 |
| Portfolio Manager | ~4000 | ~800 | 1 |
| Risk rationale (optional) | ~500 | ~200 | 0–5 |

Estimated: ~15,000 tokens/tick × 288 ticks/day ≈ 4.3M tokens/day
At claude-sonnet-4-6 pricing — track costs via usage logs and set a daily budget alert.
