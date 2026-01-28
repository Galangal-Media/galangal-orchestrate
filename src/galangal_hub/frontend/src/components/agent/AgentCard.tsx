import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatRelativeTime } from "@/lib/utils"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"
import { Monitor, FolderGit2, Clock, AlertCircle } from "lucide-react"

interface AgentCardProps {
  agent: AgentInfo
  task?: TaskState | null
  prompt?: PromptData | null
  connected?: boolean
}

export function AgentCard({ agent, task, prompt, connected = true }: AgentCardProps) {
  const hasPrompt = !!prompt

  return (
    <Link to={`/agents/${agent.agent_id}`}>
      <Card className={`transition-all hover:border-primary/50 hover:shadow-lg ${
        hasPrompt ? "border-warning/50 animate-pulse" : ""
      }`}>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg truncate">{agent.agent_id}</CardTitle>
            <Badge variant={connected ? "success" : "secondary"}>
              {connected ? "Connected" : "Disconnected"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Monitor className="h-4 w-4" />
            <span className="truncate">{agent.hostname}</span>
          </div>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <FolderGit2 className="h-4 w-4" />
            <span className="truncate">{agent.project_path}</span>
          </div>

          {task && (
            <div className="pt-2 border-t border-border">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium truncate">{task.task_name}</span>
                <Badge variant="outline">{task.stage}</Badge>
              </div>
              {task.task_type && (
                <span className="text-xs text-muted-foreground">{task.task_type}</span>
              )}
            </div>
          )}

          {hasPrompt && (
            <div className="pt-2 border-t border-warning/30">
              <div className="flex items-center gap-2 text-warning">
                <AlertCircle className="h-4 w-4" />
                <span className="text-sm font-medium">Action Required</span>
              </div>
              <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                {prompt.message}
              </p>
            </div>
          )}

          {agent.connected_at && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground pt-2">
              <Clock className="h-3 w-3" />
              <span>Connected {formatRelativeTime(agent.connected_at)}</span>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}
