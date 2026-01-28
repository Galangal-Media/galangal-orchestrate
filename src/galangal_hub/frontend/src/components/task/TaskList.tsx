import { TaskCard } from "./TaskCard"
import type { TaskState } from "@/types/api"

interface TaskListProps {
  tasks: { task: TaskState; agentId: string }[]
  emptyMessage?: string
}

export function TaskList({ tasks, emptyMessage = "No active tasks" }: TaskListProps) {
  if (tasks.length === 0) {
    return (
      <div className="text-center py-16 px-4 rounded-xl border border-dashed border-border bg-card/50">
        <p className="text-muted-foreground">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
      {tasks.map((item) => (
        <TaskCard
          key={`${item.agentId}-${item.task.task_name}`}
          task={item.task}
          agentId={item.agentId}
        />
      ))}
    </div>
  )
}
