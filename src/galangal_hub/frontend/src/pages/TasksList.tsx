import { useEffect, useState, useCallback } from "react"
import { TaskList } from "@/components/task/TaskList"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type { TaskState } from "@/types/api"

interface TaskWithAgent {
  task: TaskState
  agentId: string
}

export function TasksList() {
  const [tasks, setTasks] = useState<TaskWithAgent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { lastMessage, isConnected: wsConnected } = useWebSocket("/ws/dashboard")

  const fetchTasks = useCallback(async () => {
    try {
      const agents = await api.getAgents()
      const allTasks: TaskWithAgent[] = []
      for (const agent of agents) {
        if (agent.task && agent.connected) {
          allTasks.push({
            task: agent.task,
            agentId: agent.agent.agent_id,
          })
        }
      }
      setTasks(allTasks)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch tasks")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  useEffect(() => {
    if (lastMessage) {
      fetchTasks()
    }
  }, [lastMessage, fetchTasks])

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
        <h1 className="text-2xl font-bold tracking-tight">Tasks</h1>
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
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Active</h2>
          <span className="text-xs text-muted-foreground">({tasks.length})</span>
        </div>
        <TaskList tasks={tasks} emptyMessage="No active tasks" />
      </section>
    </div>
  )
}
