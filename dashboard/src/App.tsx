import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { useWebSocket } from './hooks/useWebSocket'
import AgentMonitor from './pages/AgentMonitor'
import Backtest from './pages/Backtest'
import Overview from './pages/Overview'
import SignalFeed from './pages/SignalFeed'
import TradeLog from './pages/TradeLog'

const queryClient = new QueryClient()

function AppRoutes() {
  useWebSocket()

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Overview />} />
        <Route path="/signals" element={<SignalFeed />} />
        <Route path="/trades" element={<TradeLog />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/agents" element={<AgentMonitor />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
