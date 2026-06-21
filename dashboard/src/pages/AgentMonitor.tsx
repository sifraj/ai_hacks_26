import { useAppStore } from '../store/useAppStore'
import type { AgentHealthStatus } from '../types'

const REGIME_COLORS: Record<string, string> = {
  RISK_ON: 'bg-profit/15 text-profit border-profit/40',
  RISK_OFF: 'bg-loss/15 text-loss border-loss/40',
  HIGH_VOLATILITY: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/40',
  RANGING: 'bg-neutral/15 text-neutral border-neutral/40',
}

const STATUS_DOT: Record<AgentHealthStatus, string> = {
  ok: 'bg-profit',
  slow: 'bg-yellow-400',
  error: 'bg-loss',
}

export default function AgentMonitor() {
  const agentStatuses = useAppStore((s) => s.agentStatuses)
  const regime = useAppStore((s) => s.regime)
  const activityLog = useAppStore((s) => s.activityLog)

  const agents = Object.values(agentStatuses)

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-gray-800 bg-card p-6">
        <p className="text-xs uppercase tracking-wide text-gray-500">Current Regime (CIO)</p>
        {regime ? (
          <div className="mt-2 flex items-center gap-4">
            <span
              className={`rounded-full border px-4 py-1 text-sm font-bold ${REGIME_COLORS[regime.regime] ?? ''}`}
            >
              {regime.regime}
            </span>
            <span className="text-sm text-gray-400">
              Posture: <span className="text-gray-200">{regime.posture}</span> ({regime.posture_multiplier}x)
            </span>
          </div>
        ) : (
          <p className="mt-2 text-sm text-gray-500">No regime assessment yet</p>
        )}
        {regime && <p className="mt-3 text-sm text-gray-400">{regime.regime_rationale}</p>}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">Agents</h2>
        {agents.length === 0 ? (
          <div className="rounded-lg border border-gray-800 bg-card p-6 text-center text-sm text-gray-500">
            No agent status events received yet
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {agents.map((agent) => (
              <div key={agent.agent_name} className="rounded-lg border border-gray-800 bg-card p-4">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-gray-100">{agent.agent_name.replace(/_/g, ' ')}</span>
                  <span className={`h-2.5 w-2.5 rounded-full ${STATUS_DOT[agent.status]}`} />
                </div>
                <dl className="mt-3 space-y-1 text-xs text-gray-400">
                  <div className="flex justify-between">
                    <dt>Last run</dt>
                    <dd>{agent.last_run_timestamp ? new Date(agent.last_run_timestamp).toLocaleTimeString() : '—'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Latency</dt>
                    <dd>{agent.last_latency_ms ? `${agent.last_latency_ms.toFixed(0)}ms` : '—'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Errors</dt>
                    <dd className={agent.error_count > 0 ? 'text-loss' : ''}>{agent.error_count}</dd>
                  </div>
                </dl>
                {agent.last_error && (
                  <p className="mt-2 truncate text-xs text-loss" title={agent.last_error}>
                    {agent.last_error}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
          Live Activity Log
        </h2>
        <div className="max-h-96 overflow-y-auto rounded-lg border border-gray-800 bg-card">
          {activityLog.length === 0 ? (
            <p className="p-6 text-center text-sm text-gray-500">No activity yet</p>
          ) : (
            <ul className="divide-y divide-gray-800/60 font-mono text-xs">
              {activityLog.map((event, i) => (
                <li key={i} className="flex gap-3 px-4 py-2 text-gray-400">
                  <span className="text-gray-500">{new Date(event.timestamp).toLocaleTimeString()}</span>
                  <span className="text-gray-200">{event.event_type}</span>
                  {event.agent_name && <span className="text-neutral">{event.agent_name}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
