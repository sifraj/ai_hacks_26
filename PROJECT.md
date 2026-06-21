# Crypto Hedge Fund — Autonomous Multi-Agent Trading Platform

> A hackathon project: a fully autonomous, multi-agent crypto trading fund where
> Claude plays the role of every research analyst and decision-maker in a real
> hedge fund's org chart — running live, 24/7, on real market data, in paper-trading
> mode.

---

## 1. The Pitch (one paragraph)

We built a hedge fund that runs itself. Instead of one model "talking about" trading,
we modeled a real fund's org chart as a pipeline of specialized Claude agents —
a Sentiment Analyst, an On-Chain Analyst, a CIO, a Portfolio Manager, a Risk Manager,
a Compliance Officer — each with a narrow mandate, its own system prompt, and *no*
authority outside its lane. They hand off structured JSON, not prose, to each other
every 5 minutes, 24/7, against live Coinbase/OKX market data. Hard risk limits
(drawdown halt, daily-loss halt, exposure caps, kill switch) are enforced in
deterministic Python code, never by an LLM — the agents can *recommend*, but they
cannot override a hard stop. It's currently live, paper-trading 10 crypto assets,
with a real-time dashboard showing every signal, decision, and trade as it happens.

---

## 2. The Problem We're Solving

LLM trading demos are usually a single prompt: "here's some data, what should I buy?"
That's a toy. A real fund has:
- **Specialized roles** — a macro strategist doesn't size positions, a risk officer
  doesn't generate ideas, a compliance officer doesn't take market views.
- **Hard, non-negotiable limits** — no fund lets a model freelance past a drawdown
  limit because it "felt confident."
- **Auditability** — every dollar moved has to trace back to *why*.

We wanted to know: can you actually architect a system of LLM agents that respects
those constraints — where the *boundaries of authority* are as important as the
intelligence — and have it run unattended, continuously, against real data?

---

## 3. System Architecture

### 3.1 The Agent Pipeline (runs every 5 minutes, fully automated)

```
┌─────────────────────────── PHASE 1: INGESTION (parallel) ───────────────────────────┐
│  Market Data (Coinbase)   │  News Sentiment (NewsAPI)   │  On-Chain (OKX)            │
└───────────────────────────┴──────────────────────────────┴────────────────────────────┘
                                        │
┌─────────────────────────── PHASE 2: RESEARCH (parallel) ─────────────────────────────┐
│  Momentum Analyst          │  Sentiment Analyst (Claude) │  On-Chain Analyst (Claude) │
│  (deterministic: RSI,      │  reads headlines, scores    │  reads funding rates/OI/   │
│  MACD, Bollinger Bands)    │  conviction per asset       │  liquidations              │
└───────────────────────────┴──────────────────────────────┴────────────────────────────┘
                                        │
                              SignalBatch (typed JSON)
                                        │
┌─────────────────────────── PHASE 3: DECISION CHAIN (sequential) ─────────────────────┐
│  CIO (Claude)         →  Portfolio Manager  →  Risk Manager   →  Compliance          │
│  reads ALL signals,      (Claude) proposes     (deterministic,   (deterministic,     │
│  sets market regime &    trades, sized by      code-enforced     code-enforced rule  │
│  posture multiplier      CIO's posture         hard limits)      book checks)        │
└───────────────────────────┴──────────────────────────────┴────────────────────────────┘
                                        │
                              Execution → Paper Fill → Portfolio State Update
                                        │
                         Broadcast to live dashboard (WebSocket)
```

**The key design decision**: research and ideation are LLM-driven; capital
preservation is not. A model can suggest a trade. It cannot approve its own trade,
size it without a formula, or override a drawdown halt — those are plain Python.

### 3.2 Hard Risk Rules (code, not prompts)
| Rule | Trigger | Action |
|---|---|---|
| RISK_001 | Drawdown from session high > 5% | Kill switch, force-close all positions |
| RISK_002 | Daily loss > 3% | Halt new positions for the **rest of the day** (sticky, survives P&L recovery) |
| RISK_003 | Single position loss > 2% of portfolio | Block adding to the loser |
| RISK_004 | Single-asset allocation > 20% | Resize down to the cap |
| RISK_005 | Total long exposure > 80% | Reject additional longs |
| RISK_006 | Kill switch active | Reject everything |

Plus a separate 6-point compliance rule book (macro-event blackout windows, exchange
status checks, minimum liquidity, duplicate-order prevention, paper-trading
confirmation, market-impact caps) — all deterministic, zero LLM involvement.

### 3.3 Tech Stack

| Layer | Technology |
|---|---|
| Agents / LLM | Claude Sonnet 4.6, Anthropic Python SDK |
| Backend | Python 3.12, FastAPI, asyncio |
| Scheduling | APScheduler (5-min tick loop) |
| Data | TimescaleDB (OHLCV time-series), Redis (live state, signal cache) |
| Market data | `ccxt` → Coinbase (public, unauthenticated) |
| On-chain data | OKX public API (funding rate, open interest, liquidations) |
| News sentiment | NewsAPI.org |
| Frontend | React 18 + TypeScript + Vite, Tailwind, Recharts, Zustand, React Query |
| Live updates | WebSocket push from backend → dashboard |
| Testing | pytest, 232 tests, all passing |

---

## 4. What Makes This Non-Trivial (the engineering, not just the prompt)

A few things that bit us — and the fixes — are worth highlighting to judges, because
they show this is a *system*, not a demo wrapper:

- **LLMs don't reliably follow "JSON only."** Every analyst occasionally wraps its
  output in markdown fences, or adds explanatory prose before/after the JSON, despite
  being told not to. We built a robust extractor (`strip_json_fences`) that scans for
  the actual JSON value anywhere in the response and discards the rest — applied
  uniformly across all four LLM-output parsing sites.
- **A naive "fallback to safe defaults on any parse failure" silently breaks the
  system.** Early on, the CIO agent was *always* defaulting to its most conservative
  regime — not because the market was bad, but because minor formatting hiccups kept
  triggering full fallback, discarding the model's real (and often good) judgment. We
  rebuilt the recovery path to normalize field-name variations and salvage the
  model's actual reasoning instead of nuking it.
- **Paper-trading accounting bugs are real bugs.** Our first implementation tracked
  positions by USD cost basis only — selling a position settled at the *entry* price,
  not the market price, silently destroying every realized gain or loss. We caught
  this with a deliberate buy → price-move → sell regression test and rebuilt the
  engine around base-asset quantity tracking (the correct way to model a position).
- **Free data sources don't replace paid ones cleanly.** Our on-chain data provider
  (CoinGlass) turned out to gate funding rate and open interest behind a paid plan we
  didn't have — it returned HTTP 200 with a "upgrade your plan" message disguised as
  data. We migrated to OKX's free public market-data API and verified real funding
  rate / open interest / liquidation data end-to-end.
- **A safety-critical check that vanishes under `-O`.** The "never place a live
  order" gate was originally a bare `assert` — Python silently strips those when run
  with optimizations enabled. Replaced with explicit, non-strippable exceptions.

We treat this list as a feature, not a confession: a hackathon project that ships
with a real bug backlog and fixes is more credible than one that claims it "just
worked."

---

## 5. Live Demo — Real Numbers (as of this build)

- **232 automated tests**, all passing, covering every agent boundary and risk rule
- **58 ticks** completed autonomously today, **155 real signals** generated, zero
  manual intervention
- **10 crypto assets** tracked end-to-end: BTC, ETH, SOL, BNB, XRP, ADA, AVAX, DOT,
  POL, LINK
- Currently regime: `RANGING` / posture `NEUTRAL` — the CIO has been correctly
  conservative because signals haven't corroborated across analysts yet (the system
  is *designed* to wait for agreement rather than force a trade)
- Full audit trail: every signal, regime call, proposed trade, risk decision,
  compliance check, and fill is logged with a complete provenance chain

### Dashboard Pages
1. **Overview** — live portfolio value, P&L, drawdown, kill-switch button (with a
   type-to-confirm modal), agent health strip
2. **Signal Feed** — live stream of every signal as it's generated, filterable by
   asset/analyst/confidence
3. **Trade Log** — every trade's full lifecycle (proposed → approved/rejected →
   filled) with expandable provenance
4. **Backtesting** — replay the full agent pipeline against historical data, with
   Sharpe/Sortino/drawdown/win-rate metrics and equity curve charts
5. **Agent Monitor** — per-agent latency, error counts, live activity log, current
   CIO regime

---

## 6. Safety Posture

- **Paper trading only, enforced in code at two separate layers** (execution agent +
  paper engine), not just configuration — and the check can't be silently disabled.
- No code path anywhere in the system is capable of submitting a real order; market
  data fetches are unauthenticated/read-only even where API keys exist.
- Kill switch is checkable three ways (file flag, Redis flag, API call) and once
  triggered cannot be cleared without a manual, deliberate reset.

---

## 7. What We'd Build Next

- Persist full signal/trade provenance to TimescaleDB (currently Redis/WebSocket
  only — survives a restart, but isn't queryable historically yet)
- Unify the backtest and live execution code paths so they can never silently diverge
- A second on-chain data source for redundancy now that we've proven the pattern
  with OKX
- Real (not paper) execution behind an explicit, separately-gated feature flag —
  by design, currently impossible without a deliberate code change

---

## 8. Suggested Slide Outline

1. **Title** — "We built a hedge fund's org chart out of Claude agents"
2. **The problem** — single-prompt trading demos vs. real fund structure (role
   separation, hard limits, audit trail)
3. **Architecture diagram** — the pipeline from §3.1 above
4. **The non-negotiable boundary** — LLMs propose, code enforces (§3.2 risk rule
   table is a great visual)
5. **Live demo** — dashboard walkthrough (Overview → Signal Feed → Trade Log →
   Agent Monitor)
6. **Engineering war stories** — pick 2–3 from §4 (the JSON-fence bug and the
   realized-P&L bug are the most visually demonstrable — show before/after numbers)
7. **Live numbers** — §5 stats, ideally refreshed right before presenting
8. **Safety design** — kill switch + paper-trading enforcement
9. **What's next**
