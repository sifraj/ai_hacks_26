import { useEffect, useMemo, useRef, useState } from 'react'
import SignalCard from '../components/SignalCard'
import { useAppStore } from '../store/useAppStore'
import type { SourceAgent } from '../types'

const ANALYSTS: SourceAgent[] = ['momentum_analyst', 'sentiment_analyst', 'onchain_analyst']

export default function SignalFeed() {
  const signals = useAppStore((s) => s.signals)
  const [assetFilter, setAssetFilter] = useState<string>('ALL')
  const [analystFilter, setAnalystFilter] = useState<string>('ALL')
  const [minConfidence, setMinConfidence] = useState(0)
  const [paused, setPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = 0
    }
  }, [signals, paused])

  const assets = useMemo(
    () => Array.from(new Set(signals.map((s) => s.asset))).sort(),
    [signals],
  )

  const filtered = useMemo(
    () =>
      signals.filter(
        (s) =>
          (assetFilter === 'ALL' || s.asset === assetFilter) &&
          (analystFilter === 'ALL' || s.source_agent === analystFilter) &&
          s.confidence_score >= minConfidence,
      ),
    [signals, assetFilter, analystFilter, minConfidence],
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-800 bg-card p-4">
        <select
          value={assetFilter}
          onChange={(e) => setAssetFilter(e.target.value)}
          className="rounded-md border border-gray-700 bg-bg px-2 py-1.5 text-sm text-gray-200"
        >
          <option value="ALL">All assets</option>
          {assets.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>

        <select
          value={analystFilter}
          onChange={(e) => setAnalystFilter(e.target.value)}
          className="rounded-md border border-gray-700 bg-bg px-2 py-1.5 text-sm text-gray-200"
        >
          <option value="ALL">All analysts</option>
          {ANALYSTS.map((a) => (
            <option key={a} value={a}>
              {a.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-sm text-gray-400">
          Min confidence
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={minConfidence}
            onChange={(e) => setMinConfidence(Number(e.target.value))}
          />
          <span className="w-10 text-gray-300">{Math.round(minConfidence * 100)}%</span>
        </label>

        <div className="ml-auto text-xs text-gray-500">
          {paused ? 'Paused (hover off to resume)' : `${filtered.length} signals`}
        </div>
      </div>

      <div
        ref={scrollRef}
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
        className="max-h-[70vh] space-y-3 overflow-y-auto"
      >
        {filtered.length === 0 ? (
          <div className="rounded-lg border border-gray-800 bg-card p-8 text-center text-sm text-gray-500">
            Waiting for signals from the agent loop...
          </div>
        ) : (
          filtered.map((signal) => <SignalCard key={signal.signal_id} signal={signal} />)
        )}
      </div>
    </div>
  )
}
