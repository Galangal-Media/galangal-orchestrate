import { useEffect, useState, useCallback } from "react"
import { Link } from "react-router-dom"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type {
  EnvironmentWithAgent,
  AgentWithState,
  CreateTaskRequest,
  GitHubIssue,
  WSMessage,
} from "@/types/api"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  GitBranch,
  Bot,
  Play,
  Square,
  Plus,
  ExternalLink,
  Loader2,
  Server,
  AlertCircle,
  Monitor,
  FolderGit2,
} from "lucide-react"

const statusVariant: Record<string, "default" | "secondary" | "destructive" | "success" | "warning"> = {
  stopped: "secondary",
  cloning: "warning",
  ready: "warning",
  starting: "warning",
  running: "success",
  error: "destructive",
}

function extractGitHubRepo(repoUrl: string): string | null {
  // Extract "owner/repo" from URLs like https://github.com/owner/repo.git
  const match = repoUrl.match(/github\.com[/:]([^/]+\/[^/.]+)/)
  return match ? match[1] : null
}

const TASK_TYPES = [
  { value: "feature", label: "Feature" },
  { value: "bug_fix", label: "Bug Fix" },
  { value: "refactor", label: "Refactor" },
  { value: "chore", label: "Chore" },
  { value: "docs", label: "Docs" },
  { value: "hotfix", label: "Hotfix" },
]

interface EnvWithAgent {
  env: EnvironmentWithAgent
  agentState?: AgentWithState
}

export function AgentsList() {
  const [envAgents, setEnvAgents] = useState<EnvWithAgent[]>([])
  const [standaloneAgents, setStandaloneAgents] = useState<AgentWithState[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [taskDialogEnv, setTaskDialogEnv] = useState<EnvWithAgent | null>(null)
  const [taskDialogAgent, setTaskDialogAgent] = useState<AgentWithState | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  // Track envs where we've called start but agent hasn't connected yet
  const [pendingStarts, setPendingStarts] = useState<Set<string>>(new Set())

  const { lastMessage, isConnected: wsConnected } = useWebSocket("/ws/dashboard")

  const fetchData = useCallback(async () => {
    try {
      const [environments, agents] = await Promise.all([
        api.getEnvironments(),
        api.getAgents(),
      ])

      // Match agents to environments
      const agentMap = new Map<string, AgentWithState>()
      const envLinkedAgentIds = new Set<string>()
      for (const a of agents) {
        agentMap.set(a.agent.agent_id, a)
      }

      const merged: EnvWithAgent[] = environments.map((env) => {
        if (env.agent_id) envLinkedAgentIds.add(env.agent_id)
        return {
          env,
          agentState: env.agent_id ? agentMap.get(env.agent_id) : undefined,
        }
      })

      // Agents not linked to any environment (connected from other machines)
      const standalone = agents.filter(
        (a) => a.connected && !envLinkedAgentIds.has(a.agent.agent_id)
      )

      // Clear pending starts for envs that now have an agent_id
      setPendingStarts((prev) => {
        const next = new Set(prev)
        for (const env of environments) {
          if (env.agent_id) next.delete(env.id)
        }
        return next.size === prev.size ? prev : next
      })

      setEnvAgents(merged)
      setStandaloneAgents(standalone)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch data")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  useEffect(() => {
    if (lastMessage) {
      try {
        const msg: WSMessage = JSON.parse(lastMessage)
        if (msg.type === "env_status" || msg.type === "refresh") {
          fetchData()
        }
      } catch {
        // ignore
      }
    }
  }, [lastMessage, fetchData])

  // Poll for updates — fast while agents are starting, slow as general fallback
  useEffect(() => {
    const intervalMs = pendingStarts.size > 0 ? 3000 : 10000
    const interval = setInterval(fetchData, intervalMs)
    return () => clearInterval(interval)
  }, [pendingStarts.size, fetchData])

  const handleStartAgent = async (envId: string) => {
    setActionLoading(envId)
    try {
      await api.startEnvironmentAgent(envId)
      setPendingStarts((prev) => new Set(prev).add(envId))
      await fetchData()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start agent")
    } finally {
      setActionLoading(null)
    }
  }

  const handleStopAgent = async (envId: string) => {
    setActionLoading(envId)
    try {
      await api.stopEnvironmentAgent(envId)
      setPendingStarts((prev) => {
        const next = new Set(prev)
        next.delete(envId)
        return next
      })
      await fetchData()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stop agent")
    } finally {
      setActionLoading(null)
    }
  }

  const handleTaskCreated = () => {
    setTaskDialogEnv(null)
    setTaskDialogAgent(null)
    fetchData()
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Agents</h1>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className={`status-dot ${wsConnected ? "status-connected" : "status-disconnected"}`} />
          <span>{wsConnected ? "Live" : "Disconnected"}</span>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Environments section */}
      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Environments</h2>
          <span className="text-xs text-muted-foreground">({envAgents.length})</span>
        </div>

        {envAgents.length === 0 ? (
          <div className="text-center py-12 px-4 rounded-lg border border-dashed border-border">
            <Server className="h-8 w-8 mx-auto mb-2 opacity-40 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No environments yet.</p>
            <p className="text-xs text-muted-foreground mt-1">
              Create one in the{" "}
              <Link to="/environments" className="text-primary hover:underline">
                Environments
              </Link>{" "}
              page to get started.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {envAgents.map((item) => (
              <EnvironmentAgentCard
                key={item.env.id}
                item={item}
                isActionLoading={actionLoading === item.env.id}
                isPendingStart={pendingStarts.has(item.env.id)}
                onStartAgent={() => handleStartAgent(item.env.id)}
                onStopAgent={() => handleStopAgent(item.env.id)}
                onNewTask={() => setTaskDialogEnv(item)}
              />
            ))}
          </div>
        )}
      </section>

      {/* Standalone agents (connected from other machines, not via an environment) */}
      {standaloneAgents.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">External Agents</h2>
            <span className="text-xs text-muted-foreground">({standaloneAgents.length})</span>
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {standaloneAgents.map((a) => (
              <StandaloneAgentCard
                key={a.agent.agent_id}
                agentState={a}
                onNewTask={() => setTaskDialogAgent(a)}
              />
            ))}
          </div>
        </section>
      )}

      {/* Task dialog for environment agents */}
      {taskDialogEnv && taskDialogEnv.agentState && (
        <CreateTaskDialog
          agentId={taskDialogEnv.agentState.agent.agent_id}
          envName={taskDialogEnv.env.name}
          githubRepo={extractGitHubRepo(taskDialogEnv.env.repo_url)}
          open={!!taskDialogEnv}
          onOpenChange={(open) => !open && setTaskDialogEnv(null)}
          onCreated={handleTaskCreated}
        />
      )}

      {/* Task dialog for standalone agents */}
      {taskDialogAgent && (
        <CreateTaskDialog
          agentId={taskDialogAgent.agent.agent_id}
          envName={taskDialogAgent.agent.project_name || taskDialogAgent.agent.hostname}
          githubRepo={null}
          open={!!taskDialogAgent}
          onOpenChange={(open) => !open && setTaskDialogAgent(null)}
          onCreated={handleTaskCreated}
        />
      )}
    </div>
  )
}

function EnvironmentAgentCard({
  item,
  isActionLoading,
  isPendingStart,
  onStartAgent,
  onStopAgent,
  onNewTask,
}: {
  item: EnvWithAgent
  isActionLoading: boolean
  isPendingStart: boolean
  onStartAgent: () => void
  onStopAgent: () => void
  onNewTask: () => void
}) {
  const { env, agentState } = item
  const agentConnected = env.agent_connected && agentState?.connected
  const agentStarting = isPendingStart || (!!env.agent_id && !agentConnected)
  const hasProfile = !!env.profile_id
  const hasTask = !!agentState?.task
  const task = agentState?.task
  const hasPrompt = !!agentState?.current_prompt

  return (
    <Card className={`${hasPrompt ? "border-warning/40" : ""}`}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <Link
              to={`/environments/${env.id}`}
              className="font-semibold text-base break-words leading-tight hover:text-primary transition-colors"
            >
              {env.name}
            </Link>
            <div className="flex items-center gap-2 mt-1.5">
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <GitBranch className="h-3 w-3 shrink-0" />
                <span className="truncate">{env.branch}</span>
              </div>
              <Badge variant={statusVariant[env.status] || "secondary"} className="text-[10px]">
                {env.status}
              </Badge>
            </div>
          </div>
          <AgentStatusBadge connected={!!agentConnected} hasAgent={!!env.agent_id} starting={agentStarting} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Current task */}
        {hasTask && task && (
          <div className="rounded-md bg-muted/50 border border-border px-3 py-2">
            <div className="flex items-center justify-between gap-2 min-w-0">
              <span className="text-sm font-medium truncate">{task.task_name}</span>
              <Badge variant="outline" className="text-[10px] shrink-0">{task.stage}</Badge>
            </div>
            {task.task_type && (
              <span className="text-[10px] text-muted-foreground">{task.task_type}</span>
            )}
          </div>
        )}

        {/* Action required prompt */}
        {hasPrompt && agentState?.current_prompt && (
          <div className="rounded-md bg-warning/8 border border-warning/20 px-3 py-2">
            <div className="flex items-center gap-1.5 text-warning">
              <span className="status-dot status-attention" />
              <span className="text-xs font-semibold">Action Required</span>
            </div>
            <p className="text-[11px] text-muted-foreground mt-1 line-clamp-2 leading-relaxed">
              {agentState.current_prompt.message}
            </p>
          </div>
        )}

        {/* Error message */}
        {env.error_message && (
          <div className="text-xs text-destructive truncate">{env.error_message}</div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 pt-1">
          {!hasProfile && !env.agent_id && !isPendingStart && (
            <p className="text-[11px] text-muted-foreground italic">
              Assign a profile in{" "}
              <Link to={`/environments/${env.id}`} className="text-primary hover:underline">
                settings
              </Link>
            </p>
          )}

          {hasProfile && !agentConnected && !agentStarting && (
            <Button
              size="sm"
              variant="default"
              className="gap-1.5 text-xs"
              onClick={(e) => {
                e.preventDefault()
                onStartAgent()
              }}
              disabled={isActionLoading}
            >
              {isActionLoading ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Play className="h-3 w-3" />
              )}
              Start Agent
            </Button>
          )}

          {agentStarting && !agentConnected && (
            <div className="flex items-center gap-2">
              <Badge variant="secondary" className="text-[10px]">
                <Loader2 className="h-3 w-3 animate-spin mr-1" />
                Connecting...
              </Badge>
              <Button
                size="sm"
                variant="ghost"
                className="gap-1 text-xs text-muted-foreground"
                onClick={(e) => {
                  e.preventDefault()
                  onStopAgent()
                }}
                disabled={isActionLoading}
              >
                <Square className="h-3 w-3" />
                Stop
              </Button>
            </div>
          )}

          {agentConnected && !hasTask && (
            <Button
              size="sm"
              variant="default"
              className="gap-1.5 text-xs"
              onClick={(e) => {
                e.preventDefault()
                onNewTask()
              }}
            >
              <Plus className="h-3 w-3" />
              New Task
            </Button>
          )}

          {agentConnected && (
            <>
              <Link to={`/agents/${agentState?.agent.agent_id}`}>
                <Button size="sm" variant="ghost" className="gap-1 text-xs">
                  <ExternalLink className="h-3 w-3" />
                  Agent
                </Button>
              </Link>
              <Button
                size="sm"
                variant="ghost"
                className="gap-1 text-xs text-muted-foreground"
                onClick={(e) => {
                  e.preventDefault()
                  onStopAgent()
                }}
                disabled={isActionLoading}
              >
                <Square className="h-3 w-3" />
                Stop
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function StandaloneAgentCard({
  agentState,
  onNewTask,
}: {
  agentState: AgentWithState
  onNewTask: () => void
}) {
  const { agent, task, current_prompt: prompt, connected } = agentState
  const hasTask = !!task
  const hasPrompt = !!prompt

  return (
    <Card className={`${hasPrompt ? "border-warning/40" : ""}`}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <Link
              to={`/agents/${agent.agent_id}`}
              className="font-semibold text-base break-words leading-tight hover:text-primary transition-colors"
            >
              {agent.project_name || agent.hostname}
            </Link>
            <div className="flex items-center gap-1.5 mt-1.5 text-xs text-muted-foreground">
              <FolderGit2 className="h-3 w-3 shrink-0" />
              <span className="truncate">{agent.project_path}</span>
            </div>
            <div className="flex items-center gap-1.5 mt-1 text-xs text-muted-foreground">
              <Monitor className="h-3 w-3 shrink-0" />
              <span className="truncate">{agent.hostname}</span>
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
      <CardContent className="space-y-3">
        {hasTask && task && (
          <div className="rounded-md bg-muted/50 border border-border px-3 py-2">
            <div className="flex items-center justify-between gap-2 min-w-0">
              <span className="text-sm font-medium truncate">{task.task_name}</span>
              <Badge variant="outline" className="text-[10px] shrink-0">{task.stage}</Badge>
            </div>
            {task.task_type && (
              <span className="text-[10px] text-muted-foreground">{task.task_type}</span>
            )}
          </div>
        )}

        {hasPrompt && prompt && (
          <div className="rounded-md bg-warning/8 border border-warning/20 px-3 py-2">
            <div className="flex items-center gap-1.5 text-warning">
              <span className="status-dot status-attention" />
              <span className="text-xs font-semibold">Action Required</span>
            </div>
            <p className="text-[11px] text-muted-foreground mt-1 line-clamp-2 leading-relaxed">
              {prompt.message}
            </p>
          </div>
        )}

        <div className="flex items-center gap-2 pt-1">
          {connected && !hasTask && (
            <Button
              size="sm"
              variant="default"
              className="gap-1.5 text-xs"
              onClick={(e) => {
                e.preventDefault()
                onNewTask()
              }}
            >
              <Plus className="h-3 w-3" />
              New Task
            </Button>
          )}
          <Link to={`/agents/${agent.agent_id}`}>
            <Button size="sm" variant="ghost" className="gap-1 text-xs">
              <ExternalLink className="h-3 w-3" />
              View
            </Button>
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}

function AgentStatusBadge({ connected, hasAgent, starting }: { connected: boolean; hasAgent: boolean; starting: boolean }) {
  if (connected) {
    return (
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="status-dot status-connected" />
        <Badge variant="success" className="text-[10px]">Connected</Badge>
      </div>
    )
  }

  if (starting || hasAgent) {
    return (
      <div className="flex items-center gap-1.5 shrink-0">
        <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
        <Badge variant="secondary" className="text-[10px]">Starting</Badge>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <Bot className="h-3.5 w-3.5 text-muted-foreground" />
      <span className="text-[10px] text-muted-foreground">No agent</span>
    </div>
  )
}

// ─── Create Task Dialog ─────────────────────────────────────────────

function CreateTaskDialog({
  agentId,
  envName,
  githubRepo,
  open,
  onOpenChange,
  onCreated,
}: {
  agentId: string
  envName: string
  githubRepo: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
}) {
  const [tab, setTab] = useState<"manual" | "github">("manual")

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New Task — {envName}</DialogTitle>
        </DialogHeader>

        {/* Tab bar */}
        <div className="flex border-b border-border">
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === "manual"
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setTab("manual")}
          >
            Manual Task
          </button>
          <button
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === "github"
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setTab("github")}
          >
            GitHub Issues
          </button>
        </div>

        {tab === "manual" ? (
          <ManualTaskForm agentId={agentId} onCreated={onCreated} />
        ) : (
          <GitHubIssuesTab agentId={agentId} githubRepo={githubRepo} onCreated={onCreated} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function ManualTaskForm({
  agentId,
  onCreated,
}: {
  agentId: string
  onCreated: () => void
}) {
  const [taskName, setTaskName] = useState("")
  const [taskDescription, setTaskDescription] = useState("")
  const [taskType, setTaskType] = useState("feature")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const request: CreateTaskRequest = {
        task_name: taskName,
        task_description: taskDescription || undefined,
        task_type: taskType,
      }
      await api.createTask(agentId, request)
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create task")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="px-3 py-2 bg-destructive/10 border border-destructive/40 rounded text-destructive text-sm">
          {error}
        </div>
      )}

      <div className="space-y-2">
        <label className="text-sm font-medium">Task Name</label>
        <Input
          value={taskName}
          onChange={(e) => setTaskName(e.target.value)}
          placeholder="fix-login-bug"
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">Description</label>
        <Textarea
          value={taskDescription}
          onChange={(e) => setTaskDescription(e.target.value)}
          placeholder="Describe what needs to be done..."
          rows={3}
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">Task Type</label>
        <Select value={taskType} onValueChange={setTaskType}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TASK_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex justify-end gap-2 pt-2">
        <Button type="submit" disabled={submitting || !taskName}>
          {submitting ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
              Creating...
            </>
          ) : (
            "Create Task"
          )}
        </Button>
      </div>
    </form>
  )
}

function GitHubIssuesTab({
  agentId,
  githubRepo,
  onCreated,
}: {
  agentId: string
  githubRepo: string | null
  onCreated: () => void
}) {
  const [issues, setIssues] = useState<GitHubIssue[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    const fetch = async () => {
      try {
        const data = await api.getGitHubIssues(agentId, true)
        if (!cancelled) {
          setIssues(data.issues)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch issues")
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetch()
    return () => { cancelled = true }
  }, [agentId])

  const handleSelectIssue = async (issue: GitHubIssue) => {
    setCreating(issue.number)
    try {
      await api.createTask(agentId, {
        github_issue: issue.number,
        github_repo: githubRepo || undefined,
      })
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create task from issue")
    } finally {
      setCreating(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        <span className="text-sm text-muted-foreground ml-2">Loading issues...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-3 py-4 text-center">
        <p className="text-sm text-destructive">{error}</p>
        <p className="text-xs text-muted-foreground mt-1">
          Make sure the repository has GitHub issues with the "galangal" label.
        </p>
      </div>
    )
  }

  if (issues.length === 0) {
    return (
      <div className="px-3 py-8 text-center">
        <p className="text-sm text-muted-foreground">No GitHub issues found.</p>
        <p className="text-xs text-muted-foreground mt-1">
          Issues with the "galangal" label will appear here.
        </p>
      </div>
    )
  }

  return (
    <div className="max-h-80 overflow-y-auto space-y-1">
      {issues.map((issue) => (
        <button
          key={issue.number}
          className="w-full text-left px-3 py-2.5 rounded-md hover:bg-muted/50 transition-colors disabled:opacity-50"
          onClick={() => handleSelectIssue(issue)}
          disabled={creating !== null}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">#{issue.number}</span>
                <span className="text-sm font-medium truncate">{issue.title}</span>
              </div>
              <div className="flex items-center gap-1.5 mt-1">
                {issue.labels.map((label) => (
                  <Badge key={label} variant="outline" className="text-[10px]">
                    {label}
                  </Badge>
                ))}
                <span className="text-[10px] text-muted-foreground">by {issue.author}</span>
              </div>
            </div>
            {creating === issue.number ? (
              <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            ) : (
              <Play className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            )}
          </div>
        </button>
      ))}
    </div>
  )
}
