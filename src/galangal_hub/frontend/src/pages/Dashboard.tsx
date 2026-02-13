import { useEffect, useState, useCallback } from "react"
import { AgentList } from "@/components/agent/AgentList"
import { TaskList } from "@/components/task/TaskList"
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

export function Dashboard() {
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

  // Refresh on WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      fetchAgents()
    }
  }, [lastMessage, fetchAgents])

  const connectedAgents = agents.filter((a) => a.connected)
  const activePrompts = agents.filter((a) => a.prompt)
  const activeTasks = agents
    .filter((a) => a.task)
    .map((a) => ({ task: a.task!, agentId: a.agent.agent_id }))

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Activity className={`h-3.5 w-3.5 ${wsConnected ? "text-success" : "text-destructive"}`} />
          <span>{wsConnected ? "Live" : "Disconnected"}</span>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {error}
        </div>
      )}

      {/* Metrics strip */}
      <div className="grid grid-cols-3 gap-px bg-border rounded-lg overflow-hidden">
        <div className="bg-card px-5 py-4">
          <div className="text-2xl font-bold tabular-nums">{connectedAgents.length}</div>
          <div className="text-xs text-muted-foreground mt-0.5">Agents connected</div>
        </div>
        <div className="bg-card px-5 py-4">
          <div className="text-2xl font-bold tabular-nums">{activeTasks.length}</div>
          <div className="text-xs text-muted-foreground mt-0.5">Active tasks</div>
        </div>
        <div className="bg-card px-5 py-4">
          <div className={`text-2xl font-bold tabular-nums ${activePrompts.length > 0 ? "text-warning" : ""}`}>
            {activePrompts.length}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">Pending actions</div>
        </div>
      </div>

      {/* Agents needing attention */}
      {activePrompts.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-warning">Needs Attention</h2>
            <span className="text-xs text-muted-foreground">({activePrompts.length})</span>
          </div>
          <AgentList agents={activePrompts} />
        </section>
      )}

      {/* All connected agents */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Connected Agents</h2>
          <span className="text-xs text-muted-foreground">({connectedAgents.length})</span>
        </div>
        <AgentList agents={connectedAgents} emptyMessage="No agents connected. Start a Galangal workflow to connect." />
      </section>

      {/* Active tasks */}
      {activeTasks.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Active Tasks</h2>
            <span className="text-xs text-muted-foreground">({activeTasks.length})</span>
          </div>
          <TaskList tasks={activeTasks} />
        </section>
      )}
    </div>
  )
}
