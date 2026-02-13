import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatRelativeTime } from "@/lib/utils"
import type { TaskState } from "@/types/api"
import { Clock, GitBranch } from "lucide-react"

interface TaskCardProps {
  task: TaskState
  agentId: string
}

const stageBadgeVariant = (stage: string): "default" | "success" | "warning" | "destructive" => {
  const lowerStage = stage.toLowerCase()
  if (lowerStage === "complete" || lowerStage === "docs") return "success"
  if (lowerStage.includes("fail") || lowerStage === "error") return "destructive"
  if (lowerStage === "pm" || lowerStage === "design") return "warning"
  return "default"
}

export function TaskCard({ task, agentId }: TaskCardProps) {
  return (
    <Link to={`/agents/${agentId}/tasks/${task.task_name}`}>
      <Card className="card-hover">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2 min-w-0">
            <div className="font-semibold text-base break-all min-w-0 leading-tight">{task.task_name}</div>
            <Badge variant={stageBadgeVariant(task.stage)} className="text-[10px] shrink-0">{task.stage}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {task.task_type && (
            <div className="text-xs text-muted-foreground">{task.task_type}</div>
          )}

          {task.branch && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground min-w-0">
              <GitBranch className="h-3 w-3 shrink-0" />
              <span className="font-mono text-[11px] truncate">{task.branch}</span>
            </div>
          )}

          {task.description && (
            <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
              {task.description}
            </p>
          )}

          {task.started_at && (
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground pt-1">
              <Clock className="h-3 w-3" />
              <span>Started {formatRelativeTime(task.started_at)}</span>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}
