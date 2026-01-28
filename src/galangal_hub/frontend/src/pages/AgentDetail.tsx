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
import { ArrowLeft, Monitor, FolderGit2, Clock, GitBranch, Target } from "lucide-react"

interface AgentDetailData {
  info: AgentInfo
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

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/">
          <Button variant="ghost" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back
          </Button>
        </Link>
        <h1 className="text-3xl font-bold">{agent.info.agent_id}</h1>
        <Badge variant={agent.connected ? "success" : "secondary"}>
          {agent.connected ? "Connected" : "Disconnected"}
        </Badge>
      </div>

      {/* Prompt Card - Show first if there's an active prompt */}
      {agent.current_prompt && agent.task && (
        <PromptCard
          prompt={agent.current_prompt}
          agentId={agent.info.agent_id}
          taskName={agent.task.task_name}
          onResponse={fetchAgent}
        />
      )}

      {/* Agent Info */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Agent Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-2">
              <Monitor className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Hostname:</span>
              <span className="text-sm text-muted-foreground">{agent.info.hostname}</span>
            </div>
            <div className="flex items-center gap-2">
              <FolderGit2 className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Project:</span>
              <span className="text-sm text-muted-foreground truncate">{agent.info.project_path}</span>
            </div>
            {agent.info.version && (
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Version:</span>
                <Badge variant="outline">{agent.info.version}</Badge>
              </div>
            )}
            {agent.info.connected_at && (
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">Connected:</span>
                <span className="text-sm text-muted-foreground">
                  {formatRelativeTime(agent.info.connected_at)}
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Task Info */}
        {agent.task && (
          <Card>
            <CardHeader>
              <CardTitle>Current Task</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-lg font-medium">{agent.task.task_name}</span>
                <Badge>{agent.task.stage}</Badge>
              </div>
              {agent.task.task_type && (
                <div className="flex items-center gap-2">
                  <Target className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{agent.task.task_type}</span>
                </div>
              )}
              {agent.task.branch && (
                <div className="flex items-center gap-2">
                  <GitBranch className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm text-muted-foreground">{agent.task.branch}</span>
                </div>
              )}
              {agent.task.description && (
                <p className="text-sm text-muted-foreground border-t border-border pt-4">
                  {agent.task.description}
                </p>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Artifacts */}
      {agent.artifacts && Object.keys(agent.artifacts).length > 0 && (
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Artifacts</h2>
          <ArtifactViewer artifacts={agent.artifacts} />
        </div>
      )}
    </div>
  )
}
