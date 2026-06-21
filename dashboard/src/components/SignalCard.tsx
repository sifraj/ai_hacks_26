import type { Signal } from '../types'
import { ConfidenceBar, DirectionBadge } from './Badges'

export default function SignalCard({ signal }: { signal: Signal }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-card p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-base font-semibold text-gray-100">{signal.asset}</span>
          <DirectionBadge direction={signal.direction} />
        </div>
        <span className="text-xs text-gray-500">{new Date(signal.timestamp).toLocaleString()}</span>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-gray-400">
        <span>
          Source: <span className="text-gray-300">{signal.source_agent.replace(/_/g, ' ')}</span>
        </span>
        <span>Horizon: {signal.horizon_hours}h</span>
      </div>

      <div className="mt-3">
        <ConfidenceBar value={signal.confidence_score} />
      </div>

      {signal.supporting_factors.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium text-profit">Supporting</p>
          <ul className="mt-1 list-inside list-disc text-xs text-gray-400">
            {signal.supporting_factors.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}

      {signal.contradicting_factors.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-medium text-loss">Contradicting</p>
          <ul className="mt-1 list-inside list-disc text-xs text-gray-400">
            {signal.contradicting_factors.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
