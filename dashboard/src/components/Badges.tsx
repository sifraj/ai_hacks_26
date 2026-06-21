import type { Direction, RiskDecisionStatus, TradeStatus } from '../types'

export function DirectionBadge({ direction }: { direction: Direction }) {
  const styles: Record<Direction, string> = {
    LONG: 'bg-profit/15 text-profit border-profit/40',
    SHORT: 'bg-loss/15 text-loss border-loss/40',
    NEUTRAL: 'bg-gray-700/40 text-gray-300 border-gray-600',
  }
  return (
    <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${styles[direction]}`}>
      {direction}
    </span>
  )
}

const TRADE_STATUS_STYLES: Record<TradeStatus, string> = {
  PROPOSED: 'bg-neutral/15 text-neutral border-neutral/40',
  APPROVED: 'bg-profit/15 text-profit border-profit/40',
  REJECTED: 'bg-loss/15 text-loss border-loss/40',
  FILLED: 'bg-gray-600/30 text-gray-200 border-gray-500',
}

export function TradeStatusBadge({ status }: { status: TradeStatus }) {
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TRADE_STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  )
}

const RISK_STATUS_STYLES: Record<RiskDecisionStatus, string> = {
  APPROVED: 'bg-profit/15 text-profit border-profit/40',
  RESIZED: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/40',
  REJECTED: 'bg-loss/15 text-loss border-loss/40',
}

export function RiskStatusBadge({ status }: { status: RiskDecisionStatus }) {
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${RISK_STATUS_STYLES[status]}`}
    >
      {status}
    </span>
  )
}

export function PnLText({ value, asPct = false }: { value: number; asPct?: boolean }) {
  const color = value > 0 ? 'text-profit' : value < 0 ? 'text-loss' : 'text-gray-400'
  const formatted = asPct
    ? `${(value * 100).toFixed(2)}%`
    : value.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
  const sign = value > 0 ? '+' : ''
  return <span className={color}>{sign}{formatted}</span>
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = pct >= 70 ? 'bg-profit' : pct >= 40 ? 'bg-neutral' : 'bg-gray-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-700">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-400">{pct}%</span>
    </div>
  )
}
