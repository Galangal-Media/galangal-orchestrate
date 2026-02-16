import { useEffect, useState } from "react"
import { api } from "@/lib/api"
import type { DopplerStatus } from "@/types/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ExternalLink, Unplug, Loader2 } from "lucide-react"

export interface DopplerSelection {
  token: string
}

interface DopplerConnectProps {
  /** Initial token when editing an existing environment */
  initial?: DopplerSelection
  /** Called whenever the connection changes */
  onChange: (selection: DopplerSelection | null) => void
}

type ConnectionState = "disconnected" | "connecting" | "validating" | "connected"

export function DopplerConnect({ initial, onChange }: DopplerConnectProps) {
  const [state, setState] = useState<ConnectionState>(
    initial?.token ? "connected" : "disconnected"
  )
  const [token, setToken] = useState(initial?.token || "")
  const [tokenInput, setTokenInput] = useState("")
  const [error, setError] = useState<string | null>(null)

  // Scope info from the service token (read-only)
  const [project, setProject] = useState<string | null>(null)
  const [config, setConfig] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // On initial mount with existing token, fetch scope info
  useEffect(() => {
    if (initial?.token && state === "connected") {
      fetchScope(initial.token)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Propagate changes up
  useEffect(() => {
    if (state === "connected" && token) {
      onChange({ token })
    } else {
      onChange(null)
    }
  }, [state, token]) // eslint-disable-line react-hooks/exhaustive-deps

  const fetchScope = async (tok: string) => {
    setLoading(true)
    try {
      const status: DopplerStatus = await api.getDopplerStatus(tok)
      setProject(status.project)
      setConfig(status.config)
    } catch {
      // Non-fatal — we still have a valid token
    } finally {
      setLoading(false)
    }
  }

  const handleConnect = () => {
    setState("connecting")
    setTokenInput("")
    setError(null)
  }

  const handleValidate = async () => {
    if (!tokenInput.trim()) {
      setError("Please enter a service token")
      return
    }
    setState("validating")
    setError(null)
    try {
      const status: DopplerStatus = await api.getDopplerStatus(tokenInput.trim())
      if (!status.authenticated) {
        setError("Token is not valid or not authenticated")
        setState("connecting")
        return
      }
      const tok = tokenInput.trim()
      setToken(tok)
      setProject(status.project)
      setConfig(status.config)
      setState("connected")
    } catch {
      setError("Failed to validate token")
      setState("connecting")
    }
  }

  const handleDisconnect = () => {
    setState("disconnected")
    setToken("")
    setTokenInput("")
    setProject(null)
    setConfig(null)
    setError(null)
  }

  // Disconnected: show connect button
  if (state === "disconnected") {
    return (
      <div className="space-y-2">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={handleConnect}
          className="gap-1.5"
        >
          Connect to Doppler
        </Button>
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
    )
  }

  // Connecting: show token input + docs link
  if (state === "connecting" || state === "validating") {
    return (
      <div className="space-y-3">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            Paste a Doppler service token
          </label>
          <div className="flex gap-2">
            <Input
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="dp.st.xxxx"
              className="font-mono text-xs flex-1"
              disabled={state === "validating"}
              onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleValidate())}
            />
            <Button
              type="button"
              size="sm"
              onClick={handleValidate}
              disabled={state === "validating" || !tokenInput.trim()}
            >
              {state === "validating" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                "Connect"
              )}
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed">
          Create a <span className="font-medium text-foreground">Service Token</span> in your{" "}
          <a
            href="https://dashboard.doppler.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            Doppler Dashboard
          </a>
          : go to your project &rarr; config &rarr; Access tab &rarr; Generate Service Token.{" "}
          <a
            href="https://docs.doppler.com/docs/service-tokens#creating-service-tokens"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            Learn more <ExternalLink className="h-3 w-3" />
          </a>
        </p>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <Button type="button" variant="ghost" size="sm" onClick={handleDisconnect} className="text-xs">
          Cancel
        </Button>
      </div>
    )
  }

  // Connected: show token + scoped project/config (read-only) + disconnect
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="success" className="text-[10px]">Connected</Badge>
        <span className="text-xs text-muted-foreground font-mono truncate max-w-[180px]">
          {token.slice(0, 12)}...
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleDisconnect}
          className="gap-1 text-xs h-6 px-2 text-muted-foreground hover:text-destructive"
        >
          <Unplug className="h-3 w-3" />
          Disconnect
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Loading token scope...
        </div>
      ) : (project || config) ? (
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {project && (
            <span>Project: <span className="font-medium text-foreground">{project}</span></span>
          )}
          {config && (
            <span>Config: <span className="font-medium text-foreground">{config}</span></span>
          )}
        </div>
      ) : null}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}
