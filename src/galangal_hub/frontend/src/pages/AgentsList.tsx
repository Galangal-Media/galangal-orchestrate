import { useEffect, useState, useCallback } from "react"
import { AgentList } from "@/components/agent/AgentList"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"

interface AgentState {
  agent: AgentInfo
  task?: TaskState | null
  prompt?: PromptData | null
  connected: boolean
}

export function AgentsList() {
  const [agents, setAgents] = useState<AgentState[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { lastMessage, isConnected: wsConnected } = useWebSocket("/ws/dashboard")

  const fetchAgents = useCallback(async () => {
    try {
      const data = await api.getAgents()
      setAgents(
        data.map((item) => ({
          agent: item.agent,
          task: item.task,
          prompt: item.current_prompt,
          connected: item.connected,
        }))
      )
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch agents")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  useEffect(() => {
    if (lastMessage) {
      fetchAgents()
    }
  }, [lastMessage, fetchAgents])

  const connectedAgents = agents.filter((a) => a.connected)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Agents</h1>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className={`status-dot ${wsConnected ? "status-connected" : "status-disconnected"}`} />
          <span>{wsConnected ? "Live" : "Disconnected"}</span>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {error}
        </div>
      )}

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Connected</h2>
          <span className="text-xs text-muted-foreground">({connectedAgents.length})</span>
        </div>
        <AgentList
          agents={connectedAgents}
          emptyMessage="No agents connected. Start a Galangal workflow to connect."
        />
      </section>
    </div>
  )
}
