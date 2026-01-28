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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Agents</h1>
        <div className="flex items-center gap-3 text-sm">
          <span className={`status-dot ${wsConnected ? "status-connected" : "status-disconnected"}`} />
          <span className="text-muted-foreground">{wsConnected ? "Live updates" : "Disconnected"}</span>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-destructive/10 border border-destructive/50 rounded-xl text-destructive">
          {error}
        </div>
      )}

      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-1 h-6 rounded-full bg-primary" />
          <h2 className="text-xl font-semibold">Connected Agents</h2>
          <span className="text-sm text-muted-foreground">({connectedAgents.length})</span>
        </div>
        <AgentList
          agents={connectedAgents}
          emptyMessage="No agents connected. Start a Galangal workflow to connect."
        />
      </section>
    </div>
  )
}
