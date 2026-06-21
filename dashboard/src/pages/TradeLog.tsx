import { Fragment, useMemo, useState } from 'react'
import { PnLText, TradeStatusBadge } from '../components/Badges'
import { useAppStore } from '../store/useAppStore'
import type { TradeLogEntry, TradeStatus } from '../types'

const STATUSES: TradeStatus[] = ['PROPOSED', 'APPROVED', 'REJECTED', 'FILLED']

function exportToCSV(trades: TradeLogEntry[]) {
  const header = ['timestamp', 'asset', 'side', 'size_usd', 'status', 'pnl_usd']
  const rows = trades.map((t) => [
    t.timestamp,
    t.asset,
    t.side,
    String(t.size_usd ?? ''),
    t.status,
    String(t.pnl_usd ?? ''),
  ])
  const csv = [header, ...rows].map((r) => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `trade_log_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function ProvenanceRow({ trade }: { trade: TradeLogEntry }) {
  return (
    <tr className="border-b border-gray-800/60 bg-bg/40">
      <td colSpan={6} className="px-4 py-4">
        <div className="grid grid-cols-2 gap-4 text-xs md:grid-cols-4">
          <div>
            <p className="font-semibold text-gray-400">Signal IDs</p>
            <p className="mt-1 text-gray-300">
              {trade.signal_ids?.length ? trade.signal_ids.join(', ') : '—'}
            </p>
          </div>
          <div>
            <p className="font-semibold text-gray-400">PM Rationale</p>
            <p className="mt-1 text-gray-300">{trade.trade_rationale ?? '—'}</p>
          </div>
          <div>
            <p className="font-semibold text-gray-400">Risk Decision</p>
            <p className="mt-1 text-gray-300">
              {trade.risk_decision
                ? `${trade.risk_decision.status} — ${trade.risk_decision.risk_rationale} (checked: ${trade.risk_decision.rules_checked.join(', ')})`
                : '—'}
            </p>
          </div>
          <div>
            <p className="font-semibold text-gray-400">Fill Details</p>
            <p className="mt-1 text-gray-300">
              {trade.fill
                ? `${trade.fill.filled_size_usd} @ $${trade.fill.fill_price} (fee $${trade.fill.fee_usd})`
                : '—'}
            </p>
          </div>
        </div>
      </td>
    </tr>
  )
}

export default function TradeLog() {
  const trades = useAppStore((s) => s.trades)
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [assetFilter, setAssetFilter] = useState<string>('ALL')
  const [expanded, setExpanded] = useState<string | null>(null)

  const assets = useMemo(() => Array.from(new Set(trades.map((t) => t.asset))).sort(), [trades])

  const filtered = useMemo(
    () =>
      trades.filter(
        (t) =>
          (statusFilter === 'ALL' || t.status === statusFilter) &&
          (assetFilter === 'ALL' || t.asset === assetFilter),
      ),
    [trades, statusFilter, assetFilter],
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-800 bg-card p-4">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-gray-700 bg-bg px-2 py-1.5 text-sm text-gray-200"
        >
          <option value="ALL">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
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
        <button
          type="button"
          onClick={() => exportToCSV(filtered)}
          className="ml-auto rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-800"
        >
          Export to CSV
        </button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-800 bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800 text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="px-4 py-3">Timestamp</th>
              <th className="px-4 py-3">Asset</th>
              <th className="px-4 py-3">Side</th>
              <th className="px-4 py-3">Size</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">P&L</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-500">
                  No trades yet
                </td>
              </tr>
            ) : (
              filtered.map((t) => (
                <Fragment key={t.proposal_id}>
                  <tr
                    key={t.proposal_id}
                    onClick={() => setExpanded(expanded === t.proposal_id ? null : t.proposal_id)}
                    className="cursor-pointer border-b border-gray-800/60 hover:bg-gray-800/30"
                  >
                    <td className="px-4 py-3 text-gray-400">
                      {new Date(t.timestamp).toLocaleString()}
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-100">{t.asset}</td>
                    <td className="px-4 py-3 text-gray-300">{t.side}</td>
                    <td className="px-4 py-3 text-gray-300">
                      {t.size_usd?.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
                    </td>
                    <td className="px-4 py-3">
                      <TradeStatusBadge status={t.status} />
                    </td>
                    <td className="px-4 py-3">
                      {t.pnl_usd !== undefined ? <PnLText value={t.pnl_usd} /> : '—'}
                    </td>
                  </tr>
                  {expanded === t.proposal_id && <ProvenanceRow key={`${t.proposal_id}-prov`} trade={t} />}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
