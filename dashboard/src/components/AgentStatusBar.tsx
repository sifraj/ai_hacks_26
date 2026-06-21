import { useAppStore } from '../store/useAppStore'
import type { AgentHealthStatus } from '../types'

const KNOWN_AGENTS = [
  'market_ingestor',
  'sentiment_ingestor',
  'onchain_ingestor',
  'momentum_analyst',
  'sentiment_analyst',
  'onchain_analyst',
  'cio_agent',
  'portfolio_manager',
  'risk_manager',
  'compliance_agent',
  'execution_agent',
  'state_manager',
]

const DOT_COLOR: Record<AgentHealthStatus, string> = {
  ok: 'bg-profit',
  slow: 'bg-yellow-400',
  error: 'bg-loss',
}

export default function AgentStatusBar() {
  const agentStatuses = useAppStore((s) => s.agentStatuses)

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-gray-800 bg-card p-4">
      {KNOWN_AGENTS.map((name) => {
        const status = agentStatuses[name]
        const health: AgentHealthStatus = status?.status ?? 'ok'
        return (
          <div
            key={name}
            title={status?.last_error ?? `${name}: ${health}`}
            className="flex items-center gap-1.5 rounded-md bg-bg px-2.5 py-1.5 text-xs text-gray-300"
          >
            <span className={`h-2 w-2 rounded-full ${DOT_COLOR[health]}`} />
            {name.replace(/_/g, ' ')}
          </div>
        )
      })}
    </div>
  )
}
