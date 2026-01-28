import { useEffect, useState, useCallback } from "react"
import { TaskList } from "@/components/task/TaskList"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type { TaskState } from "@/types/api"
import { Activity } from "lucide-react"

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
            agentId: agent.info.agent_id,
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Tasks</h1>
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

      <TaskList tasks={tasks} emptyMessage="No active tasks" />
    </div>
  )
}
