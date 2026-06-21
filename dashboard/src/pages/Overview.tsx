import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import AgentStatusBar from '../components/AgentStatusBar'
import { PnLText } from '../components/Badges'
import KillSwitchButton from '../components/KillSwitchButton'
import PositionsTable from '../components/PositionsTable'
import { useAppStore } from '../store/useAppStore'

export default function Overview() {
  const livePortfolio = useAppStore((s) => s.portfolio)

  const { data: fetchedPortfolio } = useQuery({
    queryKey: ['portfolio'],
    queryFn: api.getPortfolio,
    refetchInterval: 30_000,
  })

  const portfolio = livePortfolio ?? fetchedPortfolio

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-gray-500">Total Portfolio Value</p>
          <p className="text-4xl font-bold text-gray-100">
            {portfolio
              ? portfolio.total_value_usd.toLocaleString('en-US', { style: 'currency', currency: 'USD' })
              : '—'}
          </p>
          <div className="mt-3 flex gap-6 text-sm">
            <div>
              <span className="text-gray-500">Daily P&L: </span>
              {portfolio ? <PnLText value={portfolio.daily_pnl_usd} /> : '—'}
            </div>
            <div>
              <span className="text-gray-500">Drawdown from high: </span>
              <span className={portfolio && portfolio.drawdown_from_session_high_pct > 0.05 ? 'text-loss' : 'text-gray-300'}>
                {portfolio ? `${(portfolio.drawdown_from_session_high_pct * 100).toFixed(2)}%` : '—'}
              </span>
            </div>
            {portfolio?.kill_switch && (
              <span className="rounded-full bg-loss/15 px-3 py-0.5 text-xs font-semibold text-loss">
                KILL SWITCH ACTIVE
              </span>
            )}
          </div>
        </div>
        <KillSwitchButton />
      </div>

      <AgentStatusBar />

      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
          Positions
        </h2>
        <PositionsTable positions={portfolio?.positions ?? []} />
      </div>
    </div>
  )
}
