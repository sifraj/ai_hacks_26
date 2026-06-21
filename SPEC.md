# Crypto Hedge Fund — Agent-Native Trading Platform
## Full System Specification

> **Status:** Planning / Pre-implementation  
> **Strategy:** Multi-signal hybrid (momentum + sentiment + on-chain)  
> **Exchange:** Coinbase Advanced (paper trading first)  
> **Assets:** BTC, ETH, top 10 altcoins by market cap  
> **Deployment:** Local machine (dev/testing), Docker-ready  
> **UI:** React web dashboard + structured JSON logs  

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Agent Architecture](#2-agent-architecture)
3. [Agent Personas & Prompts](#3-agent-personas--prompts)
4. [Data Pipeline](#4-data-pipeline)
5. [Signal Schemas](#5-signal-schemas)
6. [Risk Management Rules](#6-risk-management-rules)
7. [Execution Layer](#7-execution-layer)
8. [Backtesting Engine](#8-backtesting-engine)
9. [Web Dashboard](#9-web-dashboard)
10. [Technology Stack](#10-technology-stack)
11. [Project Structure](#11-project-structure)
12. [Build Order](#12-build-order)
13. [Claude Code Implementation Guide](#13-claude-code-implementation-guide)

---

## 1. System Overview

This platform is a multi-agent autonomous trading system modeled after a real hedge fund org chart. Each agent has a defined role, authority scope, tool access, and structured I/O contract. No agent operates outside its mandate.

The system runs a continuous **agent loop** on a configurable tick interval (default: 5 minutes). Each tick:

1. Data ingestion agents fetch and normalize fresh market, sentiment, and on-chain data
2. Research analyst agents produce structured signals per asset
3. The CIO agent assesses macro regime and strategic posture
4. The Portfolio Manager synthesizes signals + posture into proposed trades
5. The Risk Manager validates and resizes proposals against hard limits
6. The Compliance agent checks proposals against rule book
7. Approved orders route to the Execution agent → Coinbase Advanced API (paper mode)
8. All decisions are logged with full provenance to structured JSON audit trail
9. The React dashboard reflects live portfolio state, signals, and agent activity

```
Market Data ──────────────────────────────────────────────┐
On-Chain Data ─────────────────────────────────────────── │
News / Social ─────────────────────────────────────────── │
                                                           ▼
                                              ┌─────────────────────┐
                                              │   Data Ingestion    │
                                              │      Agents         │
                                              └────────┬────────────┘
                                                       │ normalized data
                                                       ▼
                              ┌──────────────────────────────────────────┐
                              │           Research Analyst Agents         │
                              │  Momentum │  Sentiment  │  On-Chain      │
                              └──────────────────┬───────────────────────┘
                                                 │ SignalBatch[]
                                                 ▼
                                       ┌──────────────────┐
                                       │   CIO Agent      │
                                       │  (regime + posture)│
                                       └────────┬─────────┘
                                                │ MarketRegime + Posture
                                                ▼
                                    ┌───────────────────────┐
                                    │  Portfolio Manager    │
                                    │  Agent                │
                                    └──────────┬────────────┘
                                               │ ProposedTrade[]
                                               ▼
                                    ┌───────────────────────┐
                                    │  Risk Manager Agent   │◄── Hard Rules Engine
                                    └──────────┬────────────┘
                                               │ ApprovedTrade[] (resized)
                                               ▼
                                    ┌───────────────────────┐
                                    │  Compliance Agent     │◄── Rule Book
                                    └──────────┬────────────┘
                                               │ ClearedTrade[]
                                               ▼
                                    ┌───────────────────────┐
                                    │  Execution Agent      │
                                    └──────────┬────────────┘
                                               │
                                               ▼
                                    Coinbase Advanced API
                                    (paper trading mode)
                                               │
                                               ▼
                                    ┌───────────────────────┐
                                    │  Audit Log + State    │
                                    │  React Dashboard      │
                                    └───────────────────────┘
```

---

## 2. Agent Architecture

### 2.1 Agent Roster

| Agent | Type | LLM? | Tick Role |
|---|---|---|---|
| Market Data Ingestor | Data | No | Fetch OHLCV, order book |
| Sentiment Ingestor | Data | No | Fetch news, social feeds |
| On-Chain Ingestor | Data | No | Fetch Glassnode/on-chain metrics |
| Momentum Analyst | Research | No (computed) | Technical indicators → signals |
| Sentiment Analyst | Research | Yes (Claude) | NLP over news/social → signals |
| On-Chain Analyst | Research | Yes (Claude) | Interpret on-chain metrics → signals |
| CIO | Orchestrator | Yes (Claude) | Regime assessment + posture |
| Portfolio Manager | Decision | Yes (Claude) | Synthesize → propose trades |
| Risk Manager | Enforcement | No (rules) + Claude (explain) | Validate, resize, or reject |
| Compliance | Enforcement | No (rules) | Rule book check |
| Execution | Action | No | Place/manage orders |
| State Manager | Infrastructure | No | Portfolio state, positions |

### 2.2 Agent Loop Timing

```
Every 5 minutes (configurable):
  Phase 1 (parallel): Market + Sentiment + On-Chain ingestion
  Phase 2 (parallel): Momentum + Sentiment + On-Chain analysis
  Phase 3 (sequential): CIO → Portfolio Manager → Risk Manager → Compliance → Execution
  Phase 4: State update + audit log write + dashboard push
```

### 2.3 Inter-Agent Communication

All agents communicate via **typed JSON schemas** only. No natural language between agents. Schemas are defined in Section 5.

### 2.4 Tool Scoping

Each agent has access only to the tools its role requires:

| Agent | Allowed Tools |
|---|---|
| Ingestors | `fetch_market_data`, `fetch_news`, `fetch_onchain` |
| Analysts | `read_normalized_data`, `write_signal` |
| CIO | `read_signals`, `read_market_data`, `write_regime` |
| Portfolio Manager | `read_signals`, `read_regime`, `read_portfolio_state`, `write_proposed_trades` |
| Risk Manager | `read_proposed_trades`, `read_portfolio_state`, `write_approved_trades` |
| Compliance | `read_approved_trades`, `read_rule_book`, `write_cleared_trades` |
| Execution | `read_cleared_trades`, `place_paper_order`, `cancel_order`, `write_fill` |
| State Manager | `read_fills`, `write_portfolio_state` |

---

## 3. Agent Personas & Prompts

These are the canonical system prompts. Modify strategy details but never relax risk/compliance constraints.

### 3.1 CIO Agent

```
You are the Chief Investment Officer of an automated crypto trading fund.

ROLE: Assess current market regime and set strategic posture for the portfolio.

INPUTS: You receive a batch of signals from research analysts covering momentum, 
sentiment, and on-chain data across BTC, ETH, and top altcoins.

OUTPUTS: You produce a MarketRegime object (schema provided). Your output must be 
valid JSON matching the schema exactly. No additional text.

REGIME CLASSIFICATIONS:
- RISK_ON: Trending upward, positive sentiment, healthy on-chain activity
- RISK_OFF: Downtrending, negative sentiment, capital outflows
- HIGH_VOLATILITY: Large moves in either direction, uncertainty dominant
- RANGING: Low volatility, no clear trend, consolidation

POSTURE OPTIONS: AGGRESSIVE (1.0x base sizing), NEUTRAL (0.6x), DEFENSIVE (0.3x), FLAT (0x - no new positions)

RULES:
- In HIGH_VOLATILITY regimes, posture never exceeds NEUTRAL
- In RISK_OFF regimes, posture defaults to DEFENSIVE unless strong contradicting evidence
- You must cite at least 3 signal inputs in your regime_rationale
- When signals conflict, err conservative

Your output is MarketRegime JSON only. No preamble, no markdown.
```

### 3.2 Sentiment Analyst Agent

```
You are a Crypto Sentiment Analyst for an automated trading fund.

ROLE: Analyze news headlines and social media data to produce directional signals 
for specific crypto assets.

INPUTS: Raw text from news feeds and social data for the past 4 hours.

OUTPUTS: An array of Signal objects (schema provided). JSON only, no other text.

SIGNAL RULES:
- Only produce signals where you have genuine conviction. Omit uncertain assets.
- confidence_score: 0.0 (no conviction) to 1.0 (extremely high conviction). 
  Be conservative — most signals should be 0.4–0.7. Above 0.8 only for clear, 
  corroborated evidence.
- horizon_hours: How long you expect this signal to be relevant (1–72)
- Always populate contradicting_factors honestly. Never suppress bearish evidence 
  for an asset you're bullish on.
- Distinguish between noise and signal. Celebrity tweets are noise. 
  Regulatory announcements are signal.

You are a researcher, not a trader. You do not size positions. You flag information.
Your output is Signal[] JSON only.
```

### 3.3 On-Chain Analyst Agent

```
You are a Crypto On-Chain Analyst for an automated trading fund.

ROLE: Interpret on-chain metrics (exchange flows, whale activity, network activity, 
funding rates, open interest) to produce directional signals.

INPUTS: Normalized on-chain metrics from the last 24 hours.

OUTPUTS: Signal[] JSON only.

KEY METRICS TO INTERPRET:
- Exchange inflows (bearish pressure) vs outflows (supply reduction, bullish)
- Whale wallet accumulation or distribution
- Network transaction volume and active addresses
- Funding rates (positive = longs paying = overheated, potentially bearish)
- Open interest changes (rising OI + rising price = healthy trend)

SIGNAL RULES:
- On-chain signals are slower-moving. horizon_hours should generally be 24–168.
- High confidence (>0.75) requires multiple corroborating on-chain metrics.
- Funding rate signals are short-term exceptions (horizon 4–24h).
- Never produce a signal based on a single metric alone.

Your output is Signal[] JSON only.
```

### 3.4 Portfolio Manager Agent

```
You are the Portfolio Manager of an automated crypto trading fund.

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
Your output is ProposedTrade[] JSON only.
```

### 3.5 Risk Manager Agent

```
You are the Risk Manager of an automated crypto trading fund.

ROLE: Enforce capital preservation. Review proposed trades and approve, resize, or 
reject each one based on hard rules and current portfolio exposure.

HARD RULES (non-negotiable, cannot be overridden by any other agent):
1. Maximum portfolio drawdown: 5% from session high → HALT all trading
2. Maximum single-position loss: 2% of total paper portfolio value
3. Maximum single-asset allocation: 20% of portfolio
4. Maximum total long exposure: 80% of portfolio
5. Maximum total short exposure: 40% of portfolio (if shorts enabled)
6. No new positions if daily loss exceeds 3% of portfolio
7. Kill switch: if KILL_SWITCH flag is set in state, reject ALL trades

PROCESS:
For each ProposedTrade:
1. Check all hard rules against current PortfolioState
2. If trade violates a rule: REJECT with specific rule cited
3. If trade passes but sizing exceeds risk budget: RESIZE to compliant size
4. If trade passes all rules: APPROVE

Your output is RiskDecision[] JSON only — one decision per proposed trade.
Include risk_rationale for every decision (approve, resize, or reject).

You are the last line of defense before orders reach the market. 
Conservative decisions are always correct.
```

### 3.6 Compliance Agent (Rules Engine — not LLM)

```
Deterministic rule checks — implemented in code, not LLM:

RULE_001: No trading within 10 minutes of a scheduled macro event (FOMC, CPI, etc.)
RULE_002: No trading if Coinbase API returns degraded status
RULE_003: Asset must have >$50M 24h volume on Coinbase to be tradeable
RULE_004: No duplicate orders for same asset within same tick
RULE_005: Paper trading mode must be confirmed active before any order submission
RULE_006: Order size must not exceed 1% of asset's 24h volume (market impact limit)
```

---

## 4. Data Pipeline

### 4.1 Market Data

**Source:** Coinbase Advanced WebSocket (real-time) + REST (historical)  
**Library:** `ccxt` for normalized access  
**Frequency:** WebSocket tick-by-tick; OHLCV aggregated to 5m, 1h, 1d candles  
**Storage:** TimescaleDB (local Docker) for historical; Redis for live feed cache  

**Assets:** BTC-USD, ETH-USD, SOL-USD, BNB-USD, XRP-USD, ADA-USD, AVAX-USD, DOT-USD, MATIC-USD, LINK-USD

### 4.2 Sentiment Data

**Sources:**
- NewsAPI.org (primary — crypto news headlines, free tier: 100 req/day)
  - Query: `q=bitcoin OR ethereum OR crypto&language=en&sortBy=publishedAt`
  - One query per major asset per fetch cycle; batch where possible to stay within free tier
- Reddit API (r/cryptocurrency, r/bitcoin, r/ethereum — post titles + scores)
- Optional: Twitter/X API v2 (cashtag search)

**Frequency:** Every 15 minutes (NewsAPI free tier supports ~7 fetches/hour — stay within budget)
**API key env var:** `NEWSAPI_KEY`
**Processing:** Raw headlines + descriptions → Claude Sentiment Analyst → Signal[]  

### 4.3 On-Chain Data

**Sources:**
- Glassnode API (exchange flows, whale metrics, network activity) — free tier covers basics
- CoinGlass API (funding rates, open interest, liquidations)
- Etherscan API (ETH-specific on-chain)

**Frequency:** Every 30 minutes (on-chain data is slower-moving)  

### 4.4 Data Normalization

All data normalized to a common schema before analysts see it. Raw source data never reaches analyst agents directly — always passes through ingestors first.

---

## 5. Signal Schemas

All inter-agent data uses these TypeScript-style schemas (implement as Pydantic models in Python or Zod in TypeScript).

```typescript
// Direction of a signal
type Direction = "LONG" | "SHORT" | "NEUTRAL";

// A single analyst signal for one asset
interface Signal {
  signal_id: string;           // UUID
  timestamp: string;           // ISO 8601
  source_agent: string;        // "momentum_analyst" | "sentiment_analyst" | "onchain_analyst"
  asset: string;               // "BTC-USD"
  direction: Direction;
  confidence_score: number;    // 0.0 – 1.0
  horizon_hours: number;       // How long signal is expected to be valid
  supporting_factors: string[];
  contradicting_factors: string[];
  raw_metrics?: Record<string, number>; // Optional numeric evidence
}

// Batch of signals from one tick across all analysts
interface SignalBatch {
  tick_id: string;
  timestamp: string;
  signals: Signal[];
}

// CIO output
type Posture = "AGGRESSIVE" | "NEUTRAL" | "DEFENSIVE" | "FLAT";
type RegimeType = "RISK_ON" | "RISK_OFF" | "HIGH_VOLATILITY" | "RANGING";

interface MarketRegime {
  tick_id: string;
  timestamp: string;
  regime: RegimeType;
  posture: Posture;
  posture_multiplier: number;  // 1.0 | 0.6 | 0.3 | 0.0
  regime_rationale: string;
  signal_ids_cited: string[];  // Must cite ≥3
}

// Portfolio Manager output
type OrderSide = "BUY" | "SELL";
type OrderType = "MARKET" | "LIMIT";

interface ProposedTrade {
  proposal_id: string;
  tick_id: string;
  asset: string;
  side: OrderSide;
  order_type: OrderType;
  size_usd: number;
  limit_price?: number;        // Required if order_type is LIMIT
  stop_loss_pct: number;       // e.g. 0.02 = 2% stop
  take_profit_pct?: number;
  trade_rationale: string;
  signal_ids: string[];        // Which signals drove this proposal
  confidence_composite: number;
}

// Risk Manager output
type RiskDecision_status = "APPROVED" | "RESIZED" | "REJECTED";

interface RiskDecision {
  proposal_id: string;
  status: RiskDecision_status;
  approved_size_usd?: number;  // Present if APPROVED or RESIZED
  risk_rationale: string;
  rules_checked: string[];     // Rule IDs checked
  rules_violated?: string[];   // Present if REJECTED or RESIZED
}

// Cleared trade (post-compliance)
interface ClearedTrade {
  cleared_id: string;
  proposal_id: string;
  asset: string;
  side: OrderSide;
  order_type: OrderType;
  final_size_usd: number;
  limit_price?: number;
  stop_loss_pct: number;
  compliance_checks_passed: string[];
}

// Order fill (from execution)
interface Fill {
  fill_id: string;
  cleared_id: string;
  asset: string;
  side: OrderSide;
  filled_size_usd: number;
  fill_price: number;
  fee_usd: number;
  timestamp: string;
  paper_trade: boolean;        // Always true in current phase
}

// Live portfolio state
interface Position {
  asset: string;
  size_usd: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl_usd: number;
  unrealized_pnl_pct: number;
  stop_loss_price: number;
}

interface PortfolioState {
  timestamp: string;
  total_value_usd: number;
  cash_usd: number;
  positions: Position[];
  session_high_usd: number;
  daily_pnl_usd: number;
  daily_pnl_pct: number;
  drawdown_from_session_high_pct: number;
  kill_switch: boolean;
}
```

---

## 6. Risk Management Rules

### Hard Limits (enforced in code — never relaxed)

| Rule ID | Rule | Action on Breach |
|---|---|---|
| RISK_001 | Drawdown from session high > 5% | HALT — set kill_switch, close all positions |
| RISK_002 | Daily loss > 3% | No new positions for remainder of session |
| RISK_003 | Single position loss > 2% portfolio | Auto stop-loss triggered |
| RISK_004 | Single asset allocation > 20% portfolio | Resize to 20% cap |
| RISK_005 | Total long exposure > 80% portfolio | Reject additional longs |
| RISK_006 | Kill switch active | Reject ALL trades |

### Soft Limits (LLM-evaluated, can be overridden with rationale)

| Rule ID | Rule | Default Action |
|---|---|---|
| RISK_010 | Signal confidence composite < 0.5 | Reduce size by 50% |
| RISK_011 | Single-analyst signal (no corroboration) | Reduce size by 30% |
| RISK_012 | Asset correlation > 0.85 with existing position | Flag for PM review |

### Position Sizing Formula

```
base_size = portfolio_value * 0.05          # 5% base risk per trade
sized = base_size * posture_multiplier      # Apply CIO posture
sized = sized * confidence_composite        # Scale by signal confidence
sized = min(sized, portfolio_value * 0.20)  # Cap at 20% per asset
sized = max(sized, 500)                     # Minimum $500 paper
```

---

## 7. Execution Layer

### 7.1 Paper Trading Mode

**Phase 1 (current):** All orders simulated. A paper trading engine maintains a virtual order book and simulates fills with:
- Slippage model: 0.1% market impact for orders < 0.5% of 24h volume
- Fill latency simulation: 100–500ms random
- Fee simulation: Coinbase Advanced taker fee (0.6% base)

### 7.2 Coinbase Advanced API Integration

**Library:** `coinbase-advanced-py` (official SDK)  
**Auth:** API key + secret stored in `.env` (never committed to repo)  
**Endpoints used:**
- `GET /api/v3/brokerage/products` — asset info, volume
- `POST /api/v3/brokerage/orders` — place order (paper mode uses preview endpoint)
- `GET /api/v3/brokerage/orders/historical/batch` — order status
- `DELETE /api/v3/brokerage/orders/batch_cancel` — cancel orders
- WebSocket: `market_trades`, `ticker` channels

### 7.3 Kill Switch

Exposed as:
1. React dashboard button (requires confirmation modal)
2. `POST /api/kill-switch` REST endpoint on local server
3. File-based flag: if `./KILL_SWITCH` file exists on disk, system halts on next tick

All three set `portfolio_state.kill_switch = true` and trigger position closure.

---

## 8. Backtesting Engine

### 8.1 Architecture

```
Historical OHLCV (from TimescaleDB)
         ↓
Backtest Runner (replays ticks chronologically)
         ↓
Same agent pipeline (signals → PM → Risk → Execution)
         ↓
Paper fills with historical prices + slippage model
         ↓
Performance Report
```

### 8.2 Performance Metrics to Report

- Total return %
- Sharpe ratio (annualized)
- Sortino ratio
- Maximum drawdown (% and duration)
- Win rate (% of profitable trades)
- Average win / average loss ratio
- Calmar ratio
- Trade count, average hold time
- Per-asset breakdown
- Signal accuracy by analyst agent

### 8.3 Anti-Overfitting Rules

- Use walk-forward validation (train on months 1–6, test on 7–8, train 1–7 test 9, etc.)
- Never tune parameters on the test set
- Report out-of-sample results only in final eval
- Minimum 100 trades before drawing statistical conclusions

---

## 9. Web Dashboard

### 9.1 Pages / Views

**Overview (home)**
- Portfolio value (paper), daily P&L, session drawdown
- Active positions table with live unrealized P&L
- Kill switch button (top right, always visible)
- System status bar (all agents green/yellow/red)

**Signal Feed**
- Live stream of signals as they're generated each tick
- Filter by asset, analyst, confidence level
- Signal cards showing direction, confidence, rationale, supporting/contradicting factors

**Trade Log**
- All proposed, approved, rejected, and filled trades
- Filter by status, asset, time range
- Each row expandable to show full provenance (which signals → PM rationale → risk decision → fill)

**Backtesting**
- Run backtest over date range
- Parameter configuration
- Performance report with charts (equity curve, drawdown chart, per-asset breakdown)

**Agent Monitor**
- Live agent activity log per tick
- Latency per agent
- Error counts and last error
- Regime display (current CIO assessment)

### 9.2 Tech Stack for Dashboard

- React + TypeScript + Vite
- Tailwind CSS for styling
- Recharts for charts
- React Query for data fetching
- WebSocket connection to local backend for live updates

---

## 10. Technology Stack

### Backend

| Component | Technology | Purpose |
|---|---|---|
| Runtime | Python 3.11+ | Agent logic, data pipeline |
| Agent framework | Custom harness (see HARNESS.md) | Loop, tool routing, logging |
| LLM calls | Anthropic Python SDK (`claude-sonnet-4-6`) | CIO, PM, analysts |
| Exchange | `coinbase-advanced-py` + `ccxt` | Market data + order API |
| Task scheduling | APScheduler | 5-minute tick loop |
| Time-series DB | TimescaleDB (Docker) | Historical OHLCV storage |
| Cache | Redis (Docker) | Live feed, inter-agent state |
| Config | Pydantic Settings + `.env` | Typed config, secrets |
| Logging | `structlog` → JSON files | Structured audit trail |

### Frontend

| Component | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Build | Vite |
| Styling | Tailwind CSS |
| Charts | Recharts |
| State/fetching | React Query + Zustand |
| Live data | WebSocket (FastAPI backend) |

### Infrastructure (local)

| Component | Technology |
|---|---|
| Backend API | FastAPI (serves dashboard + WebSocket) |
| Database | TimescaleDB via Docker Compose |
| Cache | Redis via Docker Compose |
| Process management | `supervisord` or `tmux` sessions |

---

## 11. Project Structure

```
crypto-hedge-fund/
├── SPEC.md                          # This file
├── HARNESS.md                       # Agent harness implementation guide
├── CLAUDE.md                        # Claude Code instructions
├── docker-compose.yml               # TimescaleDB + Redis
├── .env.example                     # Environment variable template
├── requirements.txt
│
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py            # Abstract agent class
│   │   ├── cio_agent.py
│   │   ├── portfolio_manager.py
│   │   ├── risk_manager.py          # Rules engine, not LLM
│   │   ├── compliance_agent.py      # Rules engine, not LLM
│   │   ├── execution_agent.py
│   │   ├── state_manager.py
│   │   └── analysts/
│   │       ├── momentum_analyst.py  # Pure computation
│   │       ├── sentiment_analyst.py # LLM-powered
│   │       └── onchain_analyst.py   # LLM-powered
│   │
│   ├── ingestors/
│   │   ├── market_ingestor.py
│   │   ├── sentiment_ingestor.py
│   │   └── onchain_ingestor.py
│   │
│   ├── harness/
│   │   ├── agent_loop.py            # Main tick orchestrator
│   │   ├── tool_registry.py         # Tool scoping per agent
│   │   ├── audit_logger.py          # Structured JSON logging
│   │   └── kill_switch.py           # Kill switch monitor
│   │
│   ├── schemas/
│   │   ├── signals.py               # Pydantic models
│   │   ├── trades.py
│   │   ├── portfolio.py
│   │   └── regime.py
│   │
│   ├── paper_trading/
│   │   ├── paper_engine.py          # Simulated fills
│   │   └── slippage_model.py
│   │
│   ├── backtesting/
│   │   ├── backtest_runner.py
│   │   ├── performance_metrics.py
│   │   └── walk_forward.py
│   │
│   ├── data/
│   │   ├── timescale_client.py
│   │   ├── redis_client.py
│   │   └── migrations/
│   │
│   └── api/
│       ├── main.py                  # FastAPI app
│       ├── routers/
│       │   ├── portfolio.py
│       │   ├── signals.py
│       │   ├── trades.py
│       │   ├── backtest.py
│       │   └── control.py           # Kill switch, config
│       └── websocket.py             # Live push to dashboard
│
├── dashboard/                       # React app
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Overview.tsx
│   │   │   ├── SignalFeed.tsx
│   │   │   ├── TradeLog.tsx
│   │   │   ├── Backtesting.tsx
│   │   │   └── AgentMonitor.tsx
│   │   ├── components/
│   │   ├── hooks/
│   │   └── stores/
│   └── package.json
│
├── logs/                            # Structured JSON audit logs
├── tests/
│   ├── unit/
│   ├── integration/
│   └── backtest_fixtures/
│
└── scripts/
    ├── setup.sh                     # Initial setup
    ├── start.sh                     # Start all services
    └── kill_switch.sh               # Emergency CLI kill
```

---

## 12. Build Order

Follow this sequence strictly. Each phase must be complete and tested before moving to the next.

### Phase 1 — Foundation
- [ ] Docker Compose with TimescaleDB + Redis
- [ ] Pydantic schemas for all data types (Section 5)
- [ ] `.env` config with Pydantic Settings
- [ ] Structured JSON logger (`audit_logger.py`)
- [ ] Basic FastAPI app skeleton

### Phase 2 — Data Pipeline
- [ ] Market data ingestor (Coinbase WebSocket + REST)
- [ ] OHLCV storage in TimescaleDB
- [ ] Sentiment ingestor (CryptoPanic API)
- [ ] On-chain ingestor (CoinGlass funding rates + OI first)
- [ ] Redis cache layer

### Phase 3 — Paper Trading Engine
- [ ] Paper portfolio state (in Redis)
- [ ] Paper fill engine with slippage model
- [ ] Kill switch implementation (file + API + state flag)
- [ ] State Manager agent

### Phase 4 — Agent Harness
- [ ] Base agent class with tool registry
- [ ] Agent loop (tick orchestrator)
- [ ] Tool scoping enforcement
- [ ] Audit log integration

### Phase 5 — Research Agents
- [ ] Momentum Analyst (RSI, MACD, Bollinger Bands, volume indicators)
- [ ] Sentiment Analyst (Claude-powered NLP)
- [ ] On-Chain Analyst (Claude-powered interpretation)
- [ ] Signal validation against schema

### Phase 6 — Decision Agents
- [ ] Risk Manager (rules engine — all hard limits)
- [ ] Compliance Agent (rule book checks)
- [ ] CIO Agent (Claude-powered regime)
- [ ] Portfolio Manager (Claude-powered synthesis)
- [ ] Execution Agent (paper orders)

### Phase 7 — Backtesting
- [ ] Backtest runner (historical tick replay)
- [ ] Performance metrics calculation
- [ ] Walk-forward validation
- [ ] Initial strategy eval report

### Phase 8 — Dashboard
- [ ] React app scaffold (Vite + Tailwind)
- [ ] WebSocket connection to FastAPI
- [ ] Overview page (portfolio state)
- [ ] Signal Feed page
- [ ] Trade Log page with full provenance
- [ ] Agent Monitor page
- [ ] Kill switch UI

### Phase 9 — Hardening
- [ ] Unit tests for all schemas and risk rules
- [ ] Integration tests for full tick pipeline
- [ ] Error handling + retry logic throughout
- [ ] Rate limiter for Anthropic API calls
- [ ] Cost tracking for LLM usage per tick

---

## 13. Claude Code Implementation Guide

See `CLAUDE.md` for the complete set of prompts to use with Claude Code for each phase.

### Key implementation principles for Claude Code sessions:

**Always start a session by specifying the phase.** Example: *"We are on Phase 3 — Paper Trading Engine. Reference SPEC.md Section 7.1 and schemas in src/schemas/."*

**Reference schemas explicitly.** Claude Code should implement Pydantic models exactly matching Section 5 schemas — do not allow schema drift.

**Risk rules are sacred.** When implementing `risk_manager.py`, instruct Claude Code: *"Hard limits in SPEC.md Section 6 are non-negotiable. Implement as deterministic Python, never as LLM calls."*

**Test each agent in isolation first.** Before wiring into the loop, each agent should have a `__main__` block that runs it with fixture data.

**Never commit secrets.** `.env` is in `.gitignore`. Claude Code should only ever reference `os.getenv()` or Pydantic Settings for credentials.
