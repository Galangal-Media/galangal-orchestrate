import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatRelativeTime } from "@/lib/utils"
import type { TaskState } from "@/types/api"
import { Clock, GitBranch, Target } from "lucide-react"

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
        <CardHeader className="pb-3">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 min-w-0">
            <CardTitle className="text-lg font-semibold break-all min-w-0">{task.task_name}</CardTitle>
            <Badge variant={stageBadgeVariant(task.stage)} className="text-xs w-fit flex-shrink-0">{task.stage}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {task.task_type && (
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Target className="h-4 w-4 flex-shrink-0" />
              <span>{task.task_type}</span>
            </div>
          )}

          {task.branch && (
            <div className="flex items-center gap-3 text-sm text-muted-foreground min-w-0">
              <GitBranch className="h-4 w-4 flex-shrink-0" />
              <span className="font-mono text-xs break-all">{task.branch}</span>
            </div>
          )}

          {task.started_at && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground pt-3 mt-3 border-t border-border">
              <Clock className="h-3 w-3" />
              <span>Started {formatRelativeTime(task.started_at)}</span>
            </div>
          )}

          {task.description && (
            <p className="text-sm text-muted-foreground line-clamp-2 pt-3 mt-3 border-t border-border">
              {task.description}
            </p>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}
