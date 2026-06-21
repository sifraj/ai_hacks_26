import { NavLink, Outlet } from 'react-router-dom'
import { useAppStore } from '../store/useAppStore'

const navItems = [
  { to: '/', label: 'Overview' },
  { to: '/signals', label: 'Signal Feed' },
  { to: '/trades', label: 'Trade Log' },
  { to: '/backtest', label: 'Backtesting' },
  { to: '/agents', label: 'Agent Monitor' },
]

function WsStatusDot() {
  const status = useAppStore((s) => s.wsStatus)
  const color =
    status === 'connected' ? 'bg-profit' : status === 'connecting' ? 'bg-yellow-400' : 'bg-loss'
  const label = status === 'connected' ? 'Live' : status === 'connecting' ? 'Connecting' : 'Disconnected'
  return (
    <div className="flex items-center gap-2 text-sm text-gray-400">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      {label}
    </div>
  )
}

export default function Layout() {
  return (
    <div className="min-h-screen bg-bg text-gray-100">
      <header className="border-b border-gray-800 bg-card">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-8">
            <span className="text-lg font-semibold tracking-tight">Crypto Hedge Fund</span>
            <nav className="flex gap-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-neutral/20 text-neutral'
                        : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
          <WsStatusDot />
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}
