import { useEffect, useState, useCallback } from "react"
import { AgentList } from "@/components/agent/AgentList"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"
import { Activity } from "lucide-react"

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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Agents</h1>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Activity className={`h-4 w-4 ${wsConnected ? "text-success" : "text-destructive"}`} />
          <span>{wsConnected ? "Live" : "Disconnected"}</span>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-destructive/10 border border-destructive/50 rounded-lg text-destructive">
          {error}
        </div>
      )}

      <AgentList
        agents={connectedAgents}
        emptyMessage="No agents connected. Start a Galangal workflow to connect."
      />
    </div>
  )
}
