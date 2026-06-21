export type Direction = 'LONG' | 'SHORT' | 'NEUTRAL'
export type SourceAgent = 'momentum_analyst' | 'sentiment_analyst' | 'onchain_analyst'

export interface Signal {
  signal_id: string
  timestamp: string
  source_agent: SourceAgent
  asset: string
  direction: Direction
  confidence_score: number
  horizon_hours: number
  supporting_factors: string[]
  contradicting_factors: string[]
  raw_metrics?: Record<string, number>
}

export type RegimeType = 'RISK_ON' | 'RISK_OFF' | 'HIGH_VOLATILITY' | 'RANGING'
export type Posture = 'AGGRESSIVE' | 'NEUTRAL' | 'DEFENSIVE' | 'FLAT'

export interface MarketRegime {
  tick_id: string
  timestamp: string
  regime: RegimeType
  posture: Posture
  posture_multiplier: number
  regime_rationale: string
  signal_ids_cited: string[]
}

export type OrderSide = 'BUY' | 'SELL'
export type OrderType = 'MARKET' | 'LIMIT'

export interface ProposedTrade {
  proposal_id: string
  tick_id: string
  asset: string
  side: OrderSide
  order_type: OrderType
  size_usd: number
  limit_price?: number
  stop_loss_pct: number
  take_profit_pct?: number
  trade_rationale: string
  signal_ids: string[]
  confidence_composite: number
}

export type RiskDecisionStatus = 'APPROVED' | 'RESIZED' | 'REJECTED'

export interface RiskDecision {
  proposal_id: string
  status: RiskDecisionStatus
  approved_size_usd?: number
  risk_rationale: string
  rules_checked: string[]
  rules_violated?: string[]
}

export interface ClearedTrade {
  cleared_id: string
  proposal_id: string
  asset: string
  side: OrderSide
  order_type: OrderType
  final_size_usd: number
  limit_price?: number
  stop_loss_pct: number
  compliance_checks_passed: string[]
}

export interface Fill {
  fill_id: string
  cleared_id: string
  asset: string
  side: OrderSide
  filled_size_usd: number
  fill_price: number
  fee_usd: number
  timestamp: string
  paper_trade: boolean
}

export interface Position {
  asset: string
  size_usd: number
  entry_price: number
  current_price: number
  unrealized_pnl_usd: number
  unrealized_pnl_pct: number
  stop_loss_price: number
}

export interface PortfolioState {
  timestamp: string
  total_value_usd: number
  cash_usd: number
  positions: Position[]
  session_high_usd: number
  daily_pnl_usd: number
  daily_pnl_pct: number
  drawdown_from_session_high_pct: number
  kill_switch: boolean
}

export type TradeStatus = 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'FILLED'

export interface TradeLogEntry {
  proposal_id: string
  tick_id: string
  timestamp: string
  asset: string
  side: OrderSide
  size_usd: number
  status: TradeStatus
  pnl_usd?: number
  trade_rationale?: string
  signal_ids?: string[]
  risk_decision?: RiskDecision
  cleared_trade?: ClearedTrade
  fill?: Fill
}

export type AgentHealthStatus = 'ok' | 'slow' | 'error'

export interface AgentStatus {
  agent_name: string
  status: AgentHealthStatus
  last_run_timestamp?: string
  last_latency_ms?: number
  error_count: number
  last_error?: string
}

export interface AgentActivityEvent {
  timestamp: string
  agent_name?: string
  event_type: string
  payload?: Record<string, unknown>
}

export interface AssetBreakdown {
  asset: string
  trade_count: number
  total_pnl_usd: number
  win_rate: number
  avg_pnl_pct: number
}

export interface AnalystAccuracy {
  source_agent: string
  signal_count: number
  profitable_signal_count: number
  accuracy_pct: number
}

export interface PerformanceReport {
  total_return_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  max_drawdown_pct: number
  max_drawdown_duration_days: number
  win_rate: number
  avg_win_pct: number
  avg_loss_pct: number
  calmar_ratio: number
  total_trades: number
  avg_hold_hours: number
  per_asset: AssetBreakdown[]
  signal_accuracy_by_analyst: AnalystAccuracy[]
}

export interface BacktestResult {
  start_date: string
  end_date: string
  tick_count: number
  fills: Fill[]
  equity_curve: [string, number][]
  performance: PerformanceReport | null
}

export interface BacktestJobStatus {
  status: 'running' | 'complete' | 'failed' | 'not_found'
  result?: BacktestResult
  error?: string
}

export interface BacktestProgress {
  tick_id?: string
  timestamp?: string
  tick_count: number
  total_value_usd?: number
  window_index?: number
  window_count?: number
}

export interface WSMessage {
  event_type: string
  job_id?: string
  tick_id?: string
  timestamp?: string
  payload?: unknown
}
