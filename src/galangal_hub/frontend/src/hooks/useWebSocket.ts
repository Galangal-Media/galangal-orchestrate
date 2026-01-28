import { useEffect, useRef, useState, useCallback } from 'react'

interface UseWebSocketOptions {
  onMessage?: (data: unknown) => void
  onConnect?: () => void
  onDisconnect?: () => void
  autoConnect?: boolean
}

export function useWebSocket(url: string, options: UseWebSocketOptions = {}) {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)
  const optionsRef = useRef(options)

  // Keep options ref updated
  optionsRef.current = options

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const fullUrl = url.startsWith('/') ? `${protocol}//${window.location.host}${url}` : url
    const ws = new WebSocket(fullUrl)

    ws.onopen = () => {
      setIsConnected(true)
      optionsRef.current.onConnect?.()
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      optionsRef.current.onDisconnect?.()
      // Reconnect after 5 seconds
      reconnectTimeoutRef.current = window.setTimeout(connect, 5000)
    }

    ws.onerror = () => {
      ws.close()
    }

    ws.onmessage = (event) => {
      setLastMessage(event.data)
      try {
        const data = JSON.parse(event.data)
        optionsRef.current.onMessage?.(data)
      } catch {
        optionsRef.current.onMessage?.(event.data)
      }
    }

    wsRef.current = ws
  }, [url])

  useEffect(() => {
    if (options.autoConnect !== false) {
      connect()
    }

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      wsRef.current?.close()
    }
  }, [connect, options.autoConnect])

  const send = useCallback((data: string | object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data))
    }
  }, [])

  return { isConnected, lastMessage, send, connect }
}
