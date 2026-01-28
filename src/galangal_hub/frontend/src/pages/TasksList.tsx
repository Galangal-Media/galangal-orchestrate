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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Tasks</h1>
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
          <div className="w-1 h-6 rounded-full bg-info" />
          <h2 className="text-xl font-semibold">Active Tasks</h2>
          <span className="text-sm text-muted-foreground">({tasks.length})</span>
        </div>
        <TaskList tasks={tasks} emptyMessage="No active tasks" />
      </section>
    </div>
  )
}
