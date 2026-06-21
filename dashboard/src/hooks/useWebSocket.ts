import { useEffect, useRef } from 'react'
import { useAppStore } from '../store/useAppStore'
import type { WSMessage } from '../types'

const WS_URL = 'ws://localhost:8000/ws'
const RECONNECT_DELAY_MS = 2000

export function useWebSocket() {
  const setWsStatus = useAppStore((s) => s.setWsStatus)
  const handleWSMessage = useAppStore((s) => s.handleWSMessage)
  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closedByUserRef = useRef(false)

  useEffect(() => {
    closedByUserRef.current = false

    function connect() {
      setWsStatus('connecting')
      const socket = new WebSocket(WS_URL)
      socketRef.current = socket

      socket.onopen = () => {
        setWsStatus('connected')
      }

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WSMessage
          handleWSMessage(message)
        } catch {
          // Ignore malformed frames rather than crashing the socket handler.
        }
      }

      socket.onclose = () => {
        setWsStatus('disconnected')
        if (!closedByUserRef.current) {
          reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }

      socket.onerror = () => {
        socket.close()
      }
    }

    connect()

    return () => {
      closedByUserRef.current = true
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      socketRef.current?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
