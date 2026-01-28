import { useEffect, useState, useCallback } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AgentList } from "@/components/agent/AgentList"
import { TaskList } from "@/components/task/TaskList"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"
import { Users, ListTodo, AlertCircle, Activity } from "lucide-react"

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
          agent: item.info,
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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Dashboard</h1>
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

      {/* Stats */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Connected Agents</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{connectedAgents.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Tasks</CardTitle>
            <ListTodo className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{activeTasks.length}</div>
          </CardContent>
        </Card>
        <Card className={activePrompts.length > 0 ? "border-warning/50" : ""}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Pending Actions</CardTitle>
            <AlertCircle className={`h-4 w-4 ${activePrompts.length > 0 ? "text-warning" : "text-muted-foreground"}`} />
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${activePrompts.length > 0 ? "text-warning" : ""}`}>
              {activePrompts.length}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Agents needing attention */}
      {activePrompts.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold text-warning">Needs Attention</h2>
          <AgentList agents={activePrompts} />
        </div>
      )}

      {/* All connected agents */}
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Connected Agents</h2>
        <AgentList agents={connectedAgents} emptyMessage="No agents connected. Start a Galangal workflow to connect." />
      </div>

      {/* Active tasks */}
      {activeTasks.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Active Tasks</h2>
          <TaskList tasks={activeTasks} />
        </div>
      )}
    </div>
  )
}
