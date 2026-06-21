import { useState } from 'react'
import { API_BASE_URL } from '../api/client'

export default function KillSwitchButton() {
  const [open, setOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE_URL}/api/control/kill`, { method: 'POST' })
      if (!res.ok) throw new Error(`Request failed: ${res.status}`)
      setOpen(false)
      setConfirmText('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to trigger kill switch')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md bg-loss px-4 py-2 text-sm font-semibold text-white shadow hover:bg-red-600"
      >
        Kill Switch
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-sm rounded-lg border border-gray-700 bg-card p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-loss">Activate Kill Switch</h2>
            <p className="mt-2 text-sm text-gray-400">
              This immediately halts trading and force-closes all open positions. This action
              cannot be undone from the dashboard. Type <span className="font-mono text-gray-200">CONFIRM</span> to proceed.
            </p>
            <input
              autoFocus
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="CONFIRM"
              className="mt-4 w-full rounded-md border border-gray-700 bg-bg px-3 py-2 text-sm text-gray-100 outline-none focus:border-loss"
            />
            {error && <p className="mt-2 text-sm text-loss">{error}</p>}
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => {
                  setOpen(false)
                  setConfirmText('')
                  setError(null)
                }}
                className="rounded-md px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={confirmText !== 'CONFIRM' || submitting}
                onClick={handleConfirm}
                className="rounded-md bg-loss px-3 py-1.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {submitting ? 'Activating...' : 'Activate'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
