import { useEffect, useState, useCallback, useRef } from "react"
import { useParams, Link } from "react-router-dom"
import Markdown from "react-markdown"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PromptCard } from "@/components/prompt/PromptCard"
import { ArtifactViewer } from "@/components/artifact/ArtifactViewer"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"
import { formatRelativeTime } from "@/lib/utils"
import { ArrowLeft, GitBranch, Terminal, Clock, AlertTriangle, Loader2 } from "lucide-react"

function isStageRunning(task: TaskState): boolean {
  const stage = task.stage.toLowerCase()
  return !task.awaiting_approval && stage !== "complete" && stage !== "summary" && !stage.includes("fail") && stage !== "error" && stage !== "idle"
}

interface AgentDetailData {
  agent: AgentInfo
  task: TaskState | null
  current_prompt: PromptData | null
  artifacts: Record<string, string>
  connected: boolean
}

interface OutputLine {
  line: string
  line_type: string
}

interface ParsedOutput {
  text: string
  type: 'ai_response' | 'tool_use' | 'tool_result' | 'system' | 'result' | 'raw'
  toolName?: string
  isError?: boolean
  id?: string  // For deduplication
}

// Parse a raw JSON line into a structured output
function parseOutputLine(line: string, index: number): ParsedOutput | null {
  try {
    const data = JSON.parse(line.trim())
    const msgType = data.type || ''

    // AI text response - always show
    if (msgType === 'assistant') {
      const content = data.message?.content || []
      const results: ParsedOutput[] = []

      for (const item of content) {
        if (item.type === 'text' && item.text?.trim()) {
          // Use message id + content hash for deduplication
          const id = `${data.message?.id || index}-text-${item.text.slice(0, 50)}`
          results.push({ text: item.text.trim(), type: 'ai_response', id })
        }
        if (item.type === 'tool_use') {
          const toolName = item.name || 'Tool'
          const toolId = item.id || ''
          const input = item.input || {}
          let detail = ''
          if (toolName === 'Write' || toolName === 'Edit' || toolName === 'Read') {
            const path = input.file_path || input.path || ''
            detail = path.split('/').pop() || path
          } else if (toolName === 'Bash') {
            detail = (input.command || '').slice(0, 60)
          } else if (toolName === 'Grep' || toolName === 'Glob') {
            detail = (input.pattern || '').slice(0, 40)
          } else if (toolName === 'Task') {
            detail = input.description || 'agent'
          }
          results.push({
            text: detail ? `${toolName}: ${detail}` : toolName,
            type: 'tool_use',
            toolName,
            id: `tool-${toolId}`
          })
        }
      }
      // Return first result (we'll handle multiple in the caller later if needed)
      return results[0] || null
    }

    // Tool result - verbose only
    if (msgType === 'user') {
      const content = data.message?.content || []
      for (const item of content) {
        if (item.type === 'tool_result') {
          return {
            text: 'Tool completed',
            type: 'tool_result',
            isError: item.is_error,
            id: `result-${item.tool_use_id || index}`
          }
        }
      }
    }

    // System message - verbose only
    if (msgType === 'system') {
      const message = data.message || ''
      return { text: message, type: 'system', id: `system-${index}` }
    }

    // Final result - always show
    if (msgType === 'result') {
      return { text: data.result || 'Completed', type: 'result', id: 'final-result' }
    }

    return null
  } catch {
    // Not JSON or parse error - treat as raw
    if (line.trim()) {
      return { text: line, type: 'raw', id: `raw-${index}` }
    }
    return null
  }
}

export function TaskDetail() {
  const { agentId, taskName } = useParams<{ agentId: string; taskName: string }>()
  const [agent, setAgent] = useState<AgentDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [outputLines, setOutputLines] = useState<OutputLine[]>([])
  const [outputIndex, setOutputIndex] = useState(0)
  const outputRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [verboseMode, setVerboseMode] = useState(false)
  const [showDescription, setShowDescription] = useState(false)

  const { lastMessage } = useWebSocket("/ws/dashboard")

  const fetchAgent = useCallback(async () => {
    if (!agentId) return

    try {
      const data = await api.getAgent(agentId)
      if (taskName) {
        try {
          const artifactData = await api.getTaskArtifacts(agentId, taskName)
          data.artifacts = artifactData.artifacts
        } catch {
          // Fall back to agent payload if task artifacts endpoint is unavailable.
        }
      }
      setAgent(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch agent")
    } finally {
      setLoading(false)
    }
  }, [agentId, taskName])

  const fetchOutput = useCallback(async () => {
    if (!agentId) return

    try {
      const result = await api.getOutputLines(agentId, outputIndex)
      if (result.lines.length > 0) {
        setOutputLines(prev => [...prev, ...result.lines])
        setOutputIndex(result.next_index)
      }
    } catch {
      // Ignore output fetch errors
    }
  }, [agentId, outputIndex])

  useEffect(() => {
    fetchAgent()
    fetchOutput()
  }, [fetchAgent, fetchOutput])

  // Poll for output updates
  useEffect(() => {
    const interval = setInterval(fetchOutput, 2000)
    return () => clearInterval(interval)
  }, [fetchOutput])

  // Refresh on WebSocket messages
  useEffect(() => {
    if (lastMessage) {
      try {
        const data = JSON.parse(lastMessage)
        if (data.agent_id === agentId) {
          fetchAgent()
          if (data.type === 'output') {
            fetchOutput()
          }
        }
      } catch {
        // Ignore parse errors
      }
    }
  }, [lastMessage, agentId, fetchAgent, fetchOutput])

  // Auto-scroll output
  useEffect(() => {
    if (autoScroll && outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [outputLines, autoScroll])

  const handleScroll = () => {
    if (outputRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = outputRef.current
      const isAtBottom = scrollHeight - scrollTop - clientHeight < 50
      setAutoScroll(isAtBottom)
    }
  }

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
        <Link to={`/agents/${agentId}`}>
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Agent
          </Button>
        </Link>
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {error || "Task not found"}
        </div>
      </div>
    )
  }

  const task = agent.task
  const artifactNames = Object.keys(agent.artifacts || {}).sort((a, b) => a.localeCompare(b))

  if (!task || task.task_name !== taskName) {
    return (
      <div className="space-y-4">
        <Link to={`/agents/${agentId}`}>
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Agent
          </Button>
        </Link>
        <div className="px-4 py-3 bg-warning/10 border border-warning/40 rounded-lg text-warning text-sm">
          Task "{taskName}" is not currently active on this agent.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-3">
        <Link to={`/agents/${agentId}`}>
          <Button variant="ghost" size="sm" className="gap-1.5 text-muted-foreground">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
        </Link>
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 min-w-0">
          <h1 className="text-2xl font-bold tracking-tight break-all min-w-0">{task.task_name}</h1>
          <div className="flex items-center gap-2 w-fit shrink-0">
            {isStageRunning(task) && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
            <Badge variant="default" className="text-xs">{task.stage}</Badge>
          </div>
        </div>
        <div className="text-sm text-muted-foreground">
          {agent.agent.project_name} <span className="mx-1 opacity-40">/</span> {agent.agent.hostname}
        </div>
      </div>

      {/* Prompt Card - Show first if there's an active prompt */}
      {agent.current_prompt && (
        <PromptCard
          prompt={agent.current_prompt}
          agentId={agent.agent.agent_id}
          taskName={task.task_name}
          onResponse={fetchAgent}
        />
      )}

      {/* Task Info */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Task Details
            </CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="space-y-3 text-sm">
              {task.task_type && (
                <div className="flex items-baseline gap-3">
                  <dt className="text-muted-foreground min-w-[64px] shrink-0">Type</dt>
                  <dd><Badge variant="outline" className="text-[10px]">{task.task_type}</Badge></dd>
                </div>
              )}
              {task.branch && (
                <div className="flex items-baseline gap-3">
                  <dt className="text-muted-foreground min-w-[64px] shrink-0">Branch</dt>
                  <dd className="flex items-center gap-1.5 min-w-0">
                    <GitBranch className="h-3 w-3 text-muted-foreground shrink-0" />
                    <span className="font-mono text-xs break-all">{task.branch}</span>
                  </dd>
                </div>
              )}
              <div className="flex items-baseline gap-3">
                <dt className="text-muted-foreground min-w-[64px] shrink-0">Attempt</dt>
                <dd className="tabular-nums">{task.attempt}</dd>
              </div>
              {task.started_at && (
                <div className="flex items-baseline gap-3">
                  <dt className="text-muted-foreground min-w-[64px] shrink-0">Started</dt>
                  <dd className="flex items-center gap-1.5 text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    <span>{formatRelativeTime(task.started_at)}</span>
                  </dd>
                </div>
              )}
              {task.github_issue && task.github_repo && (
                <div className="flex items-baseline gap-3">
                  <dt className="text-muted-foreground min-w-[64px] shrink-0">Issue</dt>
                  <dd>
                    <a
                      href={`https://github.com/${task.github_repo}/issues/${task.github_issue}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary hover:underline"
                    >
                      #{task.github_issue}
                    </a>
                  </dd>
                </div>
              )}
            </dl>
          </CardContent>
        </Card>

        {/* Description & Last Failure */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Description
              </CardTitle>
              {(task.description || task.task_description) && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs h-7"
                  onClick={() => setShowDescription(!showDescription)}
                >
                  {showDescription ? "Hide" : "Show"}
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {(task.description || task.task_description) ? (
              showDescription ? (
                <div className="prose prose-sm prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-strong:text-foreground prose-code:text-primary prose-a:text-primary prose-li:text-muted-foreground">
                  <Markdown>{task.description || task.task_description}</Markdown>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground italic">
                  Click "Show" to view description
                </p>
              )
            ) : (
              <p className="text-xs text-muted-foreground italic">No description provided</p>
            )}

            {task.last_failure && (
              <div className="pt-3 border-t border-border">
                <div className="flex items-center gap-1.5 text-warning mb-1.5">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  <span className="text-xs font-semibold">Last Failure</span>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">{task.last_failure}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Live Output */}
      <section>
        <Card>
          <CardHeader className="pb-0">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
                <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  Live Output
                </CardTitle>
                <span className="text-[11px] text-muted-foreground tabular-nums">({outputLines.length})</span>
              </div>
              <div className="flex items-center gap-1.5">
                <Button
                  variant={verboseMode ? "default" : "outline"}
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => setVerboseMode(!verboseMode)}
                >
                  {verboseMode ? "Verbose" : "AI Only"}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className={`h-7 text-xs ${autoScroll ? "text-success" : "text-muted-foreground"}`}
                  onClick={() => setAutoScroll(!autoScroll)}
                >
                  {autoScroll ? "Auto-scroll" : "Scroll paused"}
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-3">
            <div
              ref={outputRef}
              onScroll={handleScroll}
              className="h-[360px] overflow-y-auto font-mono text-xs rounded-md border border-border bg-background/60 p-3"
            >
              {outputLines.length === 0 ? (
                <div className="flex items-center justify-center h-full text-muted-foreground gap-2">
                  <Terminal className="h-5 w-5 opacity-40" />
                  <span className="text-xs">Waiting for output...</span>
                </div>
              ) : (
                (() => {
                  // Parse and deduplicate output lines
                  const seenIds = new Set<string>()
                  const seenTexts = new Set<string>()

                  return outputLines.map((rawLine, index) => {
                    const parsed = parseOutputLine(rawLine.line, index)
                    if (!parsed) return null

                    // Deduplicate by ID or text content
                    if (parsed.type === 'ai_response') {
                      // For AI responses, use first 100 chars of text as dedup key
                      const textKey = parsed.text.slice(0, 100)
                      if (seenTexts.has(textKey)) return null
                      seenTexts.add(textKey)
                    } else if (parsed.id) {
                      if (seenIds.has(parsed.id)) return null
                      seenIds.add(parsed.id)
                    }

                    // In non-verbose mode, only show AI responses and results
                    if (!verboseMode && parsed.type !== 'ai_response' && parsed.type !== 'result') {
                      return null
                    }

                    // Style based on type
                    let className = 'py-0.5 '
                    let prefix = ''
                    switch (parsed.type) {
                      case 'ai_response':
                        className += 'text-foreground pl-3 border-l-2 border-primary/30'
                        break
                      case 'tool_use':
                        className += 'text-muted-foreground text-[11px]'
                        prefix = '> '
                        break
                      case 'tool_result':
                        className += parsed.isError ? 'text-destructive text-[11px]' : 'text-muted-foreground/50 text-[11px]'
                        prefix = parsed.isError ? 'ERR ' : ''
                        break
                      case 'system':
                        className += 'text-warning text-[11px]'
                        prefix = '! '
                        break
                      case 'result':
                        className += 'text-success font-medium'
                        break
                      default:
                        className += 'text-muted-foreground/40 text-[11px]'
                    }

                    return (
                      <div key={parsed.id || index} className={className}>
                        {verboseMode && prefix && <span className="opacity-50">{prefix}</span>}
                        {parsed.text}
                      </div>
                    )
                  })
                })()
              )}
            </div>
          </CardContent>
        </Card>
      </section>

      {/* Artifacts */}
      {artifactNames.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Artifacts</h2>
            <span className="text-xs text-muted-foreground tabular-nums">({artifactNames.length})</span>
          </div>
          <ArtifactViewer artifacts={agent.artifacts} />
        </section>
      )}
    </div>
  )
}
