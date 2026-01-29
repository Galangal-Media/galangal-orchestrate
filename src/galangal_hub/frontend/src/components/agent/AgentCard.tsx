import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatRelativeTime } from "@/lib/utils"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"
import { Monitor, FolderGit2, Clock } from "lucide-react"

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
      <Card className={`card-hover ${
        hasPrompt ? "border-warning/50" : ""
      }`}>
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-lg font-semibold break-words min-w-0">
              {agent.project_name || agent.hostname}
            </CardTitle>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className={`status-dot ${connected ? "status-connected" : "status-disconnected"}`} />
              <Badge variant={connected ? "success" : "secondary"} className="text-xs">
                {connected ? "Connected" : "Disconnected"}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <Monitor className="h-4 w-4 flex-shrink-0" />
            <span className="truncate">{agent.hostname}</span>
          </div>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <FolderGit2 className="h-4 w-4 flex-shrink-0" />
            <span className="truncate">{agent.project_path}</span>
          </div>

          {task && (
            <div className="pt-3 mt-3 border-t border-border">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium truncate">{task.task_name}</span>
                <Badge variant="outline" className="text-xs">{task.stage}</Badge>
              </div>
              {task.task_type && (
                <span className="text-xs text-muted-foreground mt-1 block">{task.task_type}</span>
              )}
            </div>
          )}

          {hasPrompt && (
            <div className="pt-3 mt-3 border-t border-warning/30 bg-warning/5 -mx-6 px-6 pb-4 -mb-6 rounded-b-lg">
              <div className="flex items-center gap-2 text-warning pt-3">
                <span className="status-dot status-attention" />
                <span className="text-sm font-semibold">Action Required</span>
              </div>
              <p className="text-xs text-muted-foreground mt-2 line-clamp-2">
                {prompt.message}
              </p>
            </div>
          )}

          {agent.connected_at && !hasPrompt && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground pt-3 mt-3 border-t border-border">
              <Clock className="h-3 w-3" />
              <span>Connected {formatRelativeTime(agent.connected_at)}</span>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}
