import { create } from 'zustand'
import type {
  AgentActivityEvent,
  AgentStatus,
  BacktestProgress,
  BacktestResult,
  MarketRegime,
  PortfolioState,
  Signal,
  TradeLogEntry,
  WSMessage,
} from '../types'

const MAX_SIGNALS = 200
const MAX_ACTIVITY_EVENTS = 100
const MAX_TRADES = 500

export type WSConnectionStatus = 'connecting' | 'connected' | 'disconnected'

interface AppState {
  wsStatus: WSConnectionStatus
  setWsStatus: (status: WSConnectionStatus) => void

  portfolio: PortfolioState | null
  regime: MarketRegime | null

  signals: Signal[]
  trades: TradeLogEntry[]
  agentStatuses: Record<string, AgentStatus>
  activityLog: AgentActivityEvent[]

  backtestJobId: string | null
  backtestProgress: BacktestProgress | null
  backtestResult: BacktestResult | null
  backtestError: string | null
  setBacktestJobId: (jobId: string | null) => void

  handleWSMessage: (message: WSMessage) => void
}

function upsertTrade(trades: TradeLogEntry[], incoming: Partial<TradeLogEntry>): TradeLogEntry[] {
  if (!incoming.proposal_id) return trades
  const idx = trades.findIndex((t) => t.proposal_id === incoming.proposal_id)
  if (idx === -1) {
    return [{ ...(incoming as TradeLogEntry) }, ...trades].slice(0, MAX_TRADES)
  }
  const updated = [...trades]
  updated[idx] = { ...updated[idx], ...incoming }
  return updated
}

export const useAppStore = create<AppState>((set) => ({
  wsStatus: 'connecting',
  setWsStatus: (status) => set({ wsStatus: status }),

  portfolio: null,
  regime: null,

  signals: [],
  trades: [],
  agentStatuses: {},
  activityLog: [],

  backtestJobId: null,
  backtestProgress: null,
  backtestResult: null,
  backtestError: null,
  setBacktestJobId: (jobId) =>
    set({ backtestJobId: jobId, backtestProgress: null, backtestResult: null, backtestError: null }),

  handleWSMessage: (message: WSMessage) => {
    const { event_type, payload, timestamp } = message

    const activityEvent: AgentActivityEvent = {
      timestamp: timestamp ?? new Date().toISOString(),
      event_type,
      agent_name: (payload as { agent_name?: string } | undefined)?.agent_name,
      payload: payload as Record<string, unknown> | undefined,
    }
    set((s) => ({ activityLog: [activityEvent, ...s.activityLog].slice(0, MAX_ACTIVITY_EVENTS) }))

    switch (event_type) {
      case 'portfolio_state_update':
      case 'tick_update': {
        const state = payload as PortfolioState
        set({ portfolio: state })
        break
      }
      case 'regime_update': {
        set({ regime: payload as MarketRegime })
        break
      }
      case 'signal_generated':
      case 'signal_batch': {
        const incoming = payload as Signal | { signals: Signal[] }
        const newSignals = Array.isArray((incoming as { signals?: Signal[] }).signals)
          ? (incoming as { signals: Signal[] }).signals
          : [incoming as Signal]
        set((s) => ({ signals: [...newSignals.reverse(), ...s.signals].slice(0, MAX_SIGNALS) }))
        break
      }
      case 'trade_proposed':
      case 'trade_approved':
      case 'trade_rejected':
      case 'trade_resized':
      case 'trade_cleared':
      case 'trade_filled': {
        const incoming = payload as Partial<TradeLogEntry>
        set((s) => ({ trades: upsertTrade(s.trades, incoming) }))
        break
      }
      case 'agent_status': {
        const status = payload as AgentStatus
        set((s) => ({
          agentStatuses: { ...s.agentStatuses, [status.agent_name]: status },
        }))
        break
      }
      case 'backtest_progress': {
        set({ backtestProgress: payload as BacktestProgress })
        break
      }
      case 'backtest_complete': {
        set({ backtestResult: payload as BacktestResult, backtestError: null })
        break
      }
      case 'backtest_failed': {
        const err = payload as { error?: string }
        set({ backtestError: err?.error ?? 'Backtest failed', backtestResult: null })
        break
      }
      default:
        break
    }

  },
}))
