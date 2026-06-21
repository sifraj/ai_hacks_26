import type { BacktestJobStatus, PortfolioState } from '../types'

export const API_BASE_URL = 'http://localhost:8000'

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`)
  return res.json() as Promise<T>
}

export const api = {
  getPortfolio: () => getJSON<PortfolioState>('/api/portfolio'),
  getHealth: () => getJSON<{ status: string }>('/health'),
  runBacktest: (startDate: string, endDate: string) =>
    postJSON<{ job_id: string; status: string }>('/api/backtest/run', {
      start_date: startDate,
      end_date: endDate,
    }),
  getBacktestResult: (jobId: string) =>
    getJSON<BacktestJobStatus>(`/api/backtest/results/${jobId}`),
}
