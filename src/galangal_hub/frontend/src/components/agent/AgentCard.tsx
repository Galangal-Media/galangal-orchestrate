import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { formatRelativeTime } from "@/lib/utils"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"
import { FolderGit2, Clock } from "lucide-react"

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
      <Card className={`card-hover ${hasPrompt ? "border-warning/40" : ""}`}>
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="font-semibold text-base break-words leading-tight">
                {agent.project_name || agent.hostname}
              </div>
              <div className="flex items-center gap-1.5 mt-1.5 text-xs text-muted-foreground">
                <FolderGit2 className="h-3 w-3 shrink-0" />
                <span className="truncate">{agent.project_path}</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <span className={`status-dot ${connected ? "status-connected" : "status-disconnected"}`} />
              <Badge variant={connected ? "success" : "secondary"} className="text-[10px]">
                {connected ? "Connected" : "Offline"}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-2.5">
          {task && (
            <div className="flex items-center justify-between gap-2 min-w-0">
              <span className="text-sm font-medium truncate">{task.task_name}</span>
              <Badge variant="outline" className="text-[10px] shrink-0">{task.stage}</Badge>
            </div>
          )}

          {hasPrompt && (
            <div className="rounded-md bg-warning/8 border border-warning/20 px-3 py-2.5">
              <div className="flex items-center gap-1.5 text-warning">
                <span className="status-dot status-attention" />
                <span className="text-xs font-semibold">Action Required</span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1 line-clamp-2 leading-relaxed">
                {prompt.message}
              </p>
            </div>
          )}

          {agent.connected_at && !hasPrompt && !task && (
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Clock className="h-3 w-3" />
              <span>Connected {formatRelativeTime(agent.connected_at)}</span>
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}
