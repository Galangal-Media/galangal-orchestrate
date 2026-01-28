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
      <div className="grid gap-6 md:grid-cols-3">
        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Connected Agents</CardTitle>
            <div className="p-2 rounded-lg bg-primary/10">
              <Users className="h-4 w-4 text-primary" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{connectedAgents.length}</div>
            <p className="text-xs text-muted-foreground mt-1">Active connections</p>
          </CardContent>
        </Card>
        <Card className="card-hover">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Active Tasks</CardTitle>
            <div className="p-2 rounded-lg bg-info/10">
              <ListTodo className="h-4 w-4 text-info" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{activeTasks.length}</div>
            <p className="text-xs text-muted-foreground mt-1">In progress</p>
          </CardContent>
        </Card>
        <Card className={activePrompts.length > 0 ? "border-warning/50 card-hover" : "card-hover"}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Pending Actions</CardTitle>
            <div className={`p-2 rounded-lg ${activePrompts.length > 0 ? "bg-warning/10" : "bg-muted"}`}>
              <AlertCircle className={`h-4 w-4 ${activePrompts.length > 0 ? "text-warning" : "text-muted-foreground"}`} />
            </div>
          </CardHeader>
          <CardContent>
            <div className={`text-3xl font-bold ${activePrompts.length > 0 ? "text-warning" : ""}`}>
              {activePrompts.length}
            </div>
            <p className="text-xs text-muted-foreground mt-1">Awaiting response</p>
          </CardContent>
        </Card>
      </div>

      {/* Agents needing attention */}
      {activePrompts.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-1 h-6 rounded-full bg-warning" />
            <h2 className="text-xl font-semibold text-warning">Needs Attention</h2>
          </div>
          <AgentList agents={activePrompts} />
        </section>
      )}

      {/* All connected agents */}
      <section className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-1 h-6 rounded-full bg-primary" />
          <h2 className="text-xl font-semibold">Connected Agents</h2>
        </div>
        <AgentList agents={connectedAgents} emptyMessage="No agents connected. Start a Galangal workflow to connect." />
      </section>

      {/* Active tasks */}
      {activeTasks.length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-1 h-6 rounded-full bg-info" />
            <h2 className="text-xl font-semibold">Active Tasks</h2>
          </div>
          <TaskList tasks={activeTasks} />
        </section>
      )}
    </div>
  )
}
