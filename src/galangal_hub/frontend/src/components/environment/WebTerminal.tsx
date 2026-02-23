import { useEffect, useRef, useCallback } from "react"
import { Terminal } from "@xterm/xterm"
import { FitAddon } from "@xterm/addon-fit"
import "@xterm/xterm/css/xterm.css"

interface WebTerminalProps {
  wsUrl: string
  onClose?: () => void
}

export function WebTerminal({ wsUrl, onClose }: WebTerminalProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const termRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  const sendResize = useCallback(() => {
    const term = termRef.current
    const ws = wsRef.current
    const fit = fitRef.current
    if (!term || !ws || !fit) return
    fit.fit()
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }))
    }
  }, [])

  const sendInterrupt = useCallback(() => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send("\x03") // Ctrl+C
    }
    termRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!containerRef.current) return

    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, monospace",
      theme: {
        background: "#09090b",
        foreground: "#fafafa",
        cursor: "#fafafa",
        selectionBackground: "#3f3f46",
      },
      scrollback: 5000,
      convertEol: false,
    })

    // Intercept Ctrl+C: let the browser handle copy, don't send to terminal
    term.attachCustomKeyEventHandler((event) => {
      if (event.ctrlKey && event.key === "c" && event.type === "keydown") {
        // Let the browser handle Ctrl+C (copy)
        // If there's a selection in xterm, copy it
        const sel = term.getSelection()
        if (sel) {
          navigator.clipboard.writeText(sel)
          term.clearSelection()
        }
        return false // Don't pass to terminal
      }
      // Also let Ctrl+V through for paste
      if (event.ctrlKey && event.key === "v") {
        return false
      }
      return true
    })

    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current)
    fitAddon.fit()
    termRef.current = term
    fitRef.current = fitAddon

    // Focus the terminal so keystrokes work immediately
    term.focus()

    const ws = new WebSocket(wsUrl)
    ws.binaryType = "arraybuffer"
    wsRef.current = ws

    ws.onopen = () => {
      // Send initial size
      ws.send(JSON.stringify({ resize: { cols: term.cols, rows: term.rows } }))
    }

    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(event.data))
      } else {
        term.write(event.data)
      }
    }

    ws.onclose = () => {
      term.writeln("\r\n\x1b[2m--- Session ended ---\x1b[0m")
      onCloseRef.current?.()
    }

    ws.onerror = () => {
      term.writeln("\r\n\x1b[31m--- Connection error ---\x1b[0m")
    }

    // Forward keystrokes from xterm to WebSocket
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(data)
      }
    })

    // Handle paste (binary data)
    term.onBinary((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        const buf = new Uint8Array(data.length)
        for (let i = 0; i < data.length; i++) buf[i] = data.charCodeAt(i)
        ws.send(buf)
      }
    })

    // Handle resize
    const resizeObserver = new ResizeObserver(() => {
      sendResize()
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      ws.close()
      term.dispose()
      termRef.current = null
      wsRef.current = null
      fitRef.current = null
    }
  }, [wsUrl, sendResize])

  return (
    <div className="space-y-1.5">
      <div
        ref={containerRef}
        className="rounded-md overflow-hidden border border-zinc-800"
        style={{ height: "400px" }}
      />
      <div className="flex items-center gap-2">
        <button
          onClick={sendInterrupt}
          className="inline-flex items-center gap-1 px-2 py-1 text-[11px] font-mono bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded border border-zinc-700 transition-colors"
          title="Send Ctrl+C interrupt signal to the terminal"
        >
          <kbd className="text-[10px] font-bold">^C</kbd> Interrupt
        </button>
        <span className="text-[11px] text-muted-foreground">
          Ctrl+C copies text &middot; use the button to send interrupt
        </span>
      </div>
    </div>
  )
}
