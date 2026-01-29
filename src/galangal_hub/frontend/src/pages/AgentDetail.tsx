import { useEffect, useState, useCallback } from "react"
import { useParams, Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PromptCard } from "@/components/prompt/PromptCard"
import { ArtifactViewer } from "@/components/artifact/ArtifactViewer"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"
import { formatRelativeTime } from "@/lib/utils"
import { ArrowLeft, Monitor, GitBranch, Target, ChevronRight } from "lucide-react"

interface AgentDetailData {
  agent: AgentInfo
  task: TaskState | null
  current_prompt: PromptData | null
  artifacts: Record<string, string>
  connected: boolean
}

export function AgentDetail() {
  const { agentId } = useParams<{ agentId: string }>()
  const [agent, setAgent] = useState<AgentDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const { lastMessage } = useWebSocket("/ws/dashboard")

  const fetchAgent = useCallback(async () => {
    if (!agentId) return

    try {
      const data = await api.getAgent(agentId)
      setAgent(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch agent")
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    fetchAgent()
  }, [fetchAgent])

  // Refresh on WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      try {
        const data = JSON.parse(lastMessage)
        if (data.agent_id === agentId) {
          fetchAgent()
        }
      } catch {
        // Ignore parse errors
      }
    }
  }, [lastMessage, agentId, fetchAgent])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="space-y-4">
        <Link to="/">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </Link>
        <div className="p-4 bg-destructive/10 border border-destructive/50 rounded-lg text-destructive">
          {error || "Agent not found"}
        </div>
      </div>
    )
  }

  // Display title - use project name
  const displayTitle = agent.agent.project_name || agent.agent.agent_id

  return (
    <div className="space-y-8">
      <div className="space-y-4">
        <Link to="/">
          <Button variant="ghost" size="sm" className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
        </Link>
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4">
          <h1 className="text-2xl sm:text-3xl font-bold break-words">{displayTitle}</h1>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className={`status-dot ${agent.connected ? "status-connected" : "status-disconnected"}`} />
            <Badge variant={agent.connected ? "success" : "secondary"}>
              {agent.connected ? "Connected" : "Disconnected"}
            </Badge>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          {agent.agent.hostname} &middot; <span className="font-mono text-xs break-all">{agent.agent.agent_id}</span>
        </p>
      </div>

      {/* Prompt Card - Show first if there's an active prompt */}
      {agent.current_prompt && agent.task && (
        <PromptCard
          prompt={agent.current_prompt}
          agentId={agent.agent.agent_id}
          taskName={agent.task.task_name}
          onResponse={fetchAgent}
        />
      )}

      {/* Agent Info */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="card-hover">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/10">
                <Monitor className="h-4 w-4 text-primary" />
              </div>
              Agent Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-start gap-3">
              <span className="text-sm font-medium text-muted-foreground min-w-[80px]">Hostname</span>
              <span className="text-sm">{agent.agent.hostname}</span>
            </div>
            <div className="flex flex-col sm:flex-row sm:items-start gap-1 sm:gap-3">
              <span className="text-sm font-medium text-muted-foreground sm:min-w-[80px]">Project</span>
              <span className="text-sm font-mono text-xs break-all">{agent.agent.project_path}</span>
            </div>
            {agent.agent.version && (
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-muted-foreground min-w-[80px]">Version</span>
                <Badge variant="outline" className="text-xs">{agent.agent.version}</Badge>
              </div>
            )}
            {agent.agent.connected_at && (
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-muted-foreground min-w-[80px]">Connected</span>
                <span className="text-sm text-muted-foreground">
                  {formatRelativeTime(agent.agent.connected_at)}
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Task Info - Clickable */}
        {agent.task && (
          <Link to={`/agents/${agent.agent.agent_id}/tasks/${agent.task.task_name}`}>
            <Card className="card-hover cursor-pointer group">
              <CardHeader className="pb-4">
                <CardTitle className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-info/10">
                      <Target className="h-4 w-4 text-info" />
                    </div>
                    Current Task
                  </div>
                  <ChevronRight className="h-5 w-5 text-muted-foreground group-hover:text-primary transition-colors" />
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 min-w-0">
                  <span className="text-lg font-semibold group-hover:text-primary transition-colors break-all min-w-0">{agent.task.task_name}</span>
                  <Badge className="w-fit flex-shrink-0">{agent.task.stage}</Badge>
                </div>
                {agent.task.task_type && (
                  <div className="flex items-center gap-3 text-sm text-muted-foreground">
                    <Target className="h-4 w-4 flex-shrink-0" />
                    <span>{agent.task.task_type}</span>
                  </div>
                )}
                {agent.task.branch && (
                  <div className="flex items-center gap-3 text-sm text-muted-foreground min-w-0">
                    <GitBranch className="h-4 w-4 flex-shrink-0" />
                    <span className="font-mono text-xs break-all">{agent.task.branch}</span>
                  </div>
                )}
                {agent.task.description && (
                  <p className="text-sm text-muted-foreground border-t border-border pt-4 mt-4 line-clamp-2">
                    {agent.task.description}
                  </p>
                )}
              </CardContent>
            </Card>
          </Link>
        )}
      </div>

      {/* Artifacts */}
      {agent.artifacts && Object.keys(agent.artifacts).length > 0 && (
        <section className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-1 h-6 rounded-full bg-primary" />
            <h2 className="text-xl font-semibold">Artifacts</h2>
          </div>
          <ArtifactViewer artifacts={agent.artifacts} />
        </section>
      )}
    </div>
  )
}
