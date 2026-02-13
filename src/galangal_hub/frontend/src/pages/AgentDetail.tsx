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
import { ArrowLeft, GitBranch, ChevronRight } from "lucide-react"

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
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="space-y-4">
        <Link to="/">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
        </Link>
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {error || "Agent not found"}
        </div>
      </div>
    )
  }

  // Display title - use project name
  const displayTitle = agent.agent.project_name || agent.agent.agent_id

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-3">
        <Link to="/">
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
        </Link>
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
          <h1 className="text-2xl font-bold tracking-tight break-words">{displayTitle}</h1>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className={`status-dot ${agent.connected ? "status-connected" : "status-disconnected"}`} />
            <Badge variant={agent.connected ? "success" : "secondary"} className="text-[10px]">
              {agent.connected ? "Connected" : "Disconnected"}
            </Badge>
          </div>
        </div>
        <div className="text-sm text-muted-foreground">
          {agent.agent.hostname} <span className="mx-1 opacity-40">/</span>
          <span className="font-mono text-xs break-all">{agent.agent.agent_id}</span>
        </div>
      </div>

      {/* Prompt Card - Show first if there's an active prompt */}
      {agent.current_prompt && (
        <PromptCard
          prompt={agent.current_prompt}
          agentId={agent.agent.agent_id}
          taskName={agent.task?.task_name || "_"}
          onResponse={fetchAgent}
        />
      )}

      {/* Agent Info + Task */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Agent Info
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3 text-sm">
              <div className="flex items-baseline gap-3">
                <dt className="text-muted-foreground min-w-[72px] shrink-0">Hostname</dt>
                <dd>{agent.agent.hostname}</dd>
              </div>
              <div className="flex items-baseline gap-3">
                <dt className="text-muted-foreground min-w-[72px] shrink-0">Project</dt>
                <dd className="font-mono text-xs break-all">{agent.agent.project_path}</dd>
              </div>
              {agent.agent.version && (
                <div className="flex items-baseline gap-3">
                  <dt className="text-muted-foreground min-w-[72px] shrink-0">Version</dt>
                  <dd><Badge variant="outline" className="text-[10px]">{agent.agent.version}</Badge></dd>
                </div>
              )}
              {agent.agent.connected_at && (
                <div className="flex items-baseline gap-3">
                  <dt className="text-muted-foreground min-w-[72px] shrink-0">Connected</dt>
                  <dd className="text-muted-foreground">{formatRelativeTime(agent.agent.connected_at)}</dd>
                </div>
              )}
            </dl>
          </CardContent>
        </Card>

        {/* Task Info - Clickable */}
        {agent.task && (
          <Link to={`/agents/${agent.agent.agent_id}/tasks/${agent.task.task_name}`}>
            <Card className="card-hover cursor-pointer group h-full">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                    Current Task
                  </CardTitle>
                  <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between gap-2 min-w-0">
                  <span className="text-base font-semibold group-hover:text-primary transition-colors break-all min-w-0">
                    {agent.task.task_name}
                  </span>
                  <Badge className="shrink-0 text-[10px]">{agent.task.stage}</Badge>
                </div>
                {agent.task.task_type && (
                  <div className="text-xs text-muted-foreground">{agent.task.task_type}</div>
                )}
                {agent.task.branch && (
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground min-w-0">
                    <GitBranch className="h-3 w-3 shrink-0" />
                    <span className="font-mono text-[11px] break-all">{agent.task.branch}</span>
                  </div>
                )}
                {agent.task.description && (
                  <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed pt-2 border-t border-border">
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
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Artifacts</h2>
          <ArtifactViewer artifacts={agent.artifacts} />
        </section>
      )}
    </div>
  )
}
