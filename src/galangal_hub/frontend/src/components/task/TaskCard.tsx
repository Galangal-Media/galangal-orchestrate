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
      <Card className="transition-all hover:border-primary/50 hover:shadow-lg">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg truncate">{task.task_name}</CardTitle>
            <Badge variant={stageBadgeVariant(task.stage)}>{task.stage}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {task.task_type && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Target className="h-4 w-4" />
              <span>{task.task_type}</span>
            </div>
          )}

          {task.branch && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <GitBranch className="h-4 w-4" />
              <span className="truncate">{task.branch}</span>
            </div>
          )}

          {task.started_at && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground pt-2">
              <Clock className="h-3 w-3" />
              <span>Started {formatRelativeTime(task.started_at)}</span>
            </div>
          )}

          {task.description && (
            <p className="text-sm text-muted-foreground line-clamp-2 pt-2 border-t border-border">
              {task.description}
            </p>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}
