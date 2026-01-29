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
import { ArrowLeft, GitBranch, Target, Terminal, Clock, AlertTriangle } from "lucide-react"

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
      setAgent(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch agent")
    } finally {
      setLoading(false)
    }
  }, [agentId])

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
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="space-y-4">
        <Link to={`/agents/${agentId}`}>
          <Button variant="ghost" size="sm" className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            Back to Agent
          </Button>
        </Link>
        <div className="p-4 bg-destructive/10 border border-destructive/50 rounded-xl text-destructive">
          {error || "Task not found"}
        </div>
      </div>
    )
  }

  const task = agent.task

  if (!task || task.task_name !== taskName) {
    return (
      <div className="space-y-4">
        <Link to={`/agents/${agentId}`}>
          <Button variant="ghost" size="sm" className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            Back to Agent
          </Button>
        </Link>
        <div className="p-4 bg-warning/10 border border-warning/50 rounded-xl text-warning">
          Task "{taskName}" is not currently active on this agent.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="space-y-4">
        <Link to={`/agents/${agentId}`}>
          <Button variant="ghost" size="sm" className="gap-2">
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
        </Link>
        <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 min-w-0">
          <h1 className="text-2xl sm:text-3xl font-bold break-all min-w-0">{task.task_name}</h1>
          <Badge variant="default" className="text-sm w-fit flex-shrink-0">{task.stage}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          {agent.agent.project_name} &middot; {agent.agent.hostname}
        </p>
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
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="card-hover">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-info/10">
                <Target className="h-4 w-4 text-info" />
              </div>
              Task Details
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {task.task_type && (
              <div className="flex items-start gap-3">
                <span className="text-sm font-medium text-muted-foreground min-w-[80px]">Type</span>
                <Badge variant="outline" className="text-xs">{task.task_type}</Badge>
              </div>
            )}
            {task.branch && (
              <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3">
                <span className="text-sm font-medium text-muted-foreground sm:min-w-[80px]">Branch</span>
                <div className="flex items-center gap-2 min-w-0">
                  <GitBranch className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                  <span className="font-mono text-xs break-all">{task.branch}</span>
                </div>
              </div>
            )}
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-muted-foreground min-w-[80px]">Attempt</span>
              <span className="text-sm">{task.attempt}</span>
            </div>
            {task.started_at && (
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-muted-foreground min-w-[80px]">Started</span>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Clock className="h-4 w-4" />
                  <span>{formatRelativeTime(task.started_at)}</span>
                </div>
              </div>
            )}
            {task.github_issue && task.github_repo && (
              <div className="flex items-center gap-3">
                <span className="text-sm font-medium text-muted-foreground min-w-[80px]">Issue</span>
                <a
                  href={`https://github.com/${task.github_repo}/issues/${task.github_issue}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-primary hover:underline"
                >
                  #{task.github_issue}
                </a>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Description & Last Failure */}
        <Card className="card-hover">
          <CardHeader className="pb-4">
            <CardTitle className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-lg bg-primary/10">
                  <Target className="h-4 w-4 text-primary" />
                </div>
                Description
              </div>
              {(task.description || task.task_description) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowDescription(!showDescription)}
                >
                  {showDescription ? "Hide" : "Show"}
                </Button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {(task.description || task.task_description) ? (
              showDescription ? (
                <div className="prose prose-sm prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-strong:text-foreground prose-code:text-primary prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-muted prose-pre:border prose-pre:border-border prose-a:text-primary prose-li:text-muted-foreground">
                  <Markdown>{task.description || task.task_description}</Markdown>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground italic">
                  Click "Show" to view description
                </p>
              )
            ) : (
              <p className="text-sm text-muted-foreground italic">No description provided</p>
            )}

            {task.last_failure && (
              <div className="pt-4 border-t border-border">
                <div className="flex items-center gap-2 text-warning mb-2">
                  <AlertTriangle className="h-4 w-4" />
                  <span className="text-sm font-medium">Last Failure</span>
                </div>
                <p className="text-sm text-muted-foreground">{task.last_failure}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Live Output */}
      <section className="space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <div className="w-1 h-6 rounded-full bg-success" />
            <h2 className="text-xl font-semibold">Live Output</h2>
            <span className="text-sm text-muted-foreground">({outputLines.length} lines)</span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant={verboseMode ? "default" : "outline"}
              size="sm"
              onClick={() => setVerboseMode(!verboseMode)}
            >
              {verboseMode ? "Verbose" : "AI Only"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setAutoScroll(!autoScroll)}
              className={autoScroll ? "text-success" : "text-muted-foreground"}
            >
              {autoScroll ? "Auto-scroll ON" : "Auto-scroll OFF"}
            </Button>
          </div>
        </div>
        <Card>
          <CardContent className="p-0">
            <div
              ref={outputRef}
              onScroll={handleScroll}
              className="h-[400px] overflow-y-auto font-mono text-xs p-4 bg-background/50"
            >
              {outputLines.length === 0 ? (
                <div className="flex items-center justify-center h-full text-muted-foreground">
                  <Terminal className="h-8 w-8 mr-3 opacity-50" />
                  <span>Waiting for output...</span>
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
                    let className = 'py-1 '
                    let icon = ''
                    switch (parsed.type) {
                      case 'ai_response':
                        className += 'text-foreground pl-4 border-l-2 border-primary/30'
                        icon = '💬 '
                        break
                      case 'tool_use':
                        className += 'text-muted-foreground text-[11px]'
                        icon = '🔧 '
                        break
                      case 'tool_result':
                        className += parsed.isError ? 'text-destructive text-[11px]' : 'text-muted-foreground/60 text-[11px]'
                        icon = parsed.isError ? '❌ ' : '✓ '
                        break
                      case 'system':
                        className += 'text-warning text-[11px]'
                        icon = '⚡ '
                        break
                      case 'result':
                        className += 'text-success font-medium'
                        icon = '✅ '
                        break
                      default:
                        className += 'text-muted-foreground/50 text-[11px]'
                    }

                    return (
                      <div key={parsed.id || index} className={className}>
                        {verboseMode && <span className="opacity-60">{icon}</span>}
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
