import type { Position } from '../types'
import { PnLText } from './Badges'

export default function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return (
      <div className="rounded-lg border border-gray-800 bg-card p-6 text-center text-sm text-gray-500">
        No open positions
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-800 bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800 text-left text-xs uppercase tracking-wide text-gray-500">
            <th className="px-4 py-3">Asset</th>
            <th className="px-4 py-3">Size (USD)</th>
            <th className="px-4 py-3">Entry</th>
            <th className="px-4 py-3">Current</th>
            <th className="px-4 py-3">Unrealized P&L</th>
            <th className="px-4 py-3">Stop Loss</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.asset} className="border-b border-gray-800/60 last:border-0">
              <td className="px-4 py-3 font-medium text-gray-100">{p.asset}</td>
              <td className="px-4 py-3 text-gray-300">
                {p.size_usd.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
              </td>
              <td className="px-4 py-3 text-gray-300">${p.entry_price.toLocaleString()}</td>
              <td className="px-4 py-3 text-gray-300">${p.current_price.toLocaleString()}</td>
              <td className="px-4 py-3">
                <PnLText value={p.unrealized_pnl_usd} /> (<PnLText value={p.unrealized_pnl_pct} asPct />)
              </td>
              <td className="px-4 py-3 text-gray-400">${p.stop_loss_price.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
