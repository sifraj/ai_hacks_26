import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'
import { useAppStore } from '../store/useAppStore'

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-gray-100">{value}</p>
    </div>
  )
}

export default function Backtest() {
  const [startDate, setStartDate] = useState('2025-01-01')
  const [endDate, setEndDate] = useState('2025-03-01')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const backtestJobId = useAppStore((s) => s.backtestJobId)
  const setBacktestJobId = useAppStore((s) => s.setBacktestJobId)
  const progress = useAppStore((s) => s.backtestProgress)
  const result = useAppStore((s) => s.backtestResult)
  const error = useAppStore((s) => s.backtestError)

  const equityData = useMemo(
    () =>
      (result?.equity_curve ?? []).map(([ts, value]) => ({
        timestamp: new Date(ts).toLocaleDateString(),
        value,
      })),
    [result],
  )

  const drawdownData = useMemo(() => {
    const curve = result?.equity_curve ?? []
    let peak = -Infinity
    return curve.map(([ts, value]) => {
      peak = Math.max(peak, value)
      const ddPct = peak > 0 ? ((peak - value) / peak) * 100 : 0
      return { timestamp: new Date(ts).toLocaleDateString(), drawdown: -ddPct }
    })
  }, [result])

  async function handleRun() {
    setSubmitting(true)
    setSubmitError(null)
    try {
      const { job_id } = await api.runBacktest(
        new Date(startDate).toISOString(),
        new Date(endDate).toISOString(),
      )
      setBacktestJobId(job_id)
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Failed to start backtest')
    } finally {
      setSubmitting(false)
    }
  }

  const isRunning = backtestJobId !== null && !result && !error

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-gray-800 bg-card p-4">
        <label className="flex flex-col gap-1 text-sm text-gray-400">
          Start date
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="rounded-md border border-gray-700 bg-bg px-2 py-1.5 text-gray-200"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-gray-400">
          End date
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="rounded-md border border-gray-700 bg-bg px-2 py-1.5 text-gray-200"
          />
        </label>
        <button
          type="button"
          onClick={handleRun}
          disabled={submitting || isRunning}
          className="rounded-md bg-neutral px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {isRunning ? 'Running...' : 'Run Backtest'}
        </button>
        {submitError && <span className="text-sm text-loss">{submitError}</span>}
      </div>

      {isRunning && (
        <div className="rounded-lg border border-gray-800 bg-card p-4">
          <div className="flex items-center justify-between text-sm text-gray-400">
            <span>Backtest in progress...</span>
            <span>{progress?.tick_count ?? 0} ticks processed</span>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-800">
            <div className="h-full w-1/3 animate-pulse bg-neutral" />
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-loss/40 bg-loss/10 p-4 text-sm text-loss">
          Backtest failed: {error}
        </div>
      )}

      {result?.performance && (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <MetricCard label="Total Return" value={`${(result.performance.total_return_pct * 100).toFixed(2)}%`} />
            <MetricCard label="Sharpe Ratio" value={result.performance.sharpe_ratio.toFixed(2)} />
            <MetricCard label="Max Drawdown" value={`${(result.performance.max_drawdown_pct * 100).toFixed(2)}%`} />
            <MetricCard label="Win Rate" value={`${(result.performance.win_rate * 100).toFixed(1)}%`} />
            <MetricCard label="Sortino Ratio" value={result.performance.sortino_ratio.toFixed(2)} />
            <MetricCard label="Calmar Ratio" value={result.performance.calmar_ratio.toFixed(2)} />
            <MetricCard label="Trade Count" value={String(result.performance.total_trades)} />
            <MetricCard label="Avg Hold Time" value={`${result.performance.avg_hold_hours.toFixed(1)}h`} />
          </div>

          <div className="rounded-lg border border-gray-800 bg-card p-4">
            <h3 className="mb-3 text-sm font-semibold text-gray-300">Equity Curve</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={equityData}>
                <CartesianGrid stroke="#2e303a" strokeDasharray="3 3" />
                <XAxis dataKey="timestamp" stroke="#6b7280" tick={{ fontSize: 11 }} />
                <YAxis stroke="#6b7280" tick={{ fontSize: 11 }} domain={['auto', 'auto']} />
                <Tooltip contentStyle={{ background: '#1a1d27', border: '1px solid #2e303a' }} />
                <Line type="monotone" dataKey="value" stroke="#00d084" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="rounded-lg border border-gray-800 bg-card p-4">
            <h3 className="mb-3 text-sm font-semibold text-gray-300">Drawdown</h3>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={drawdownData}>
                <CartesianGrid stroke="#2e303a" strokeDasharray="3 3" />
                <XAxis dataKey="timestamp" stroke="#6b7280" tick={{ fontSize: 11 }} />
                <YAxis stroke="#6b7280" tick={{ fontSize: 11 }} />
                <Tooltip contentStyle={{ background: '#1a1d27', border: '1px solid #2e303a' }} />
                <Line type="monotone" dataKey="drawdown" stroke="#ff4757" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="overflow-x-auto rounded-lg border border-gray-800 bg-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-left text-xs uppercase tracking-wide text-gray-500">
                  <th className="px-4 py-3">Asset</th>
                  <th className="px-4 py-3">Trades</th>
                  <th className="px-4 py-3">Total P&L</th>
                  <th className="px-4 py-3">Win Rate</th>
                  <th className="px-4 py-3">Avg P&L %</th>
                </tr>
              </thead>
              <tbody>
                {result.performance.per_asset.map((row) => (
                  <tr key={row.asset} className="border-b border-gray-800/60 last:border-0">
                    <td className="px-4 py-3 font-medium text-gray-100">{row.asset}</td>
                    <td className="px-4 py-3 text-gray-300">{row.trade_count}</td>
                    <td className={`px-4 py-3 ${row.total_pnl_usd >= 0 ? 'text-profit' : 'text-loss'}`}>
                      ${row.total_pnl_usd.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-gray-300">{(row.win_rate * 100).toFixed(1)}%</td>
                    <td className="px-4 py-3 text-gray-300">{(row.avg_pnl_pct * 100).toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
