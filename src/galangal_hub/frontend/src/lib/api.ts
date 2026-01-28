import type {
  AgentWithState,
  CreateTaskRequest,
  GitHubIssue,
  QAAnswer,
  TaskRecord,
  WorkflowEvent,
} from '@/types/api'

const BASE_URL = '/api'

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// Agents
async function getAgents(): Promise<AgentWithState[]> {
  return fetchJson<AgentWithState[]>(`${BASE_URL}/agents`)
}

async function getAgent(agentId: string): Promise<AgentWithState> {
  return fetchJson<AgentWithState>(`${BASE_URL}/agents/${agentId}`)
}

// Tasks
async function getTasks(agentId: string): Promise<TaskRecord[]> {
  return fetchJson<TaskRecord[]>(`${BASE_URL}/tasks/${agentId}`)
}

async function getRecentTasks(limit: number = 20): Promise<TaskRecord[]> {
  return fetchJson<TaskRecord[]>(`${BASE_URL}/tasks/recent?limit=${limit}`)
}

// Events
async function getEvents(agentId: string, limit: number = 50): Promise<WorkflowEvent[]> {
  return fetchJson<WorkflowEvent[]>(`${BASE_URL}/agents/${agentId}/events?limit=${limit}`)
}

// Actions
async function approveTask(agentId: string, taskName: string, feedback?: string): Promise<void> {
  await fetchJson(`${BASE_URL}/actions/${agentId}/${taskName}/approve`, {
    method: 'POST',
    body: JSON.stringify({ feedback }),
  })
}

async function rejectTask(agentId: string, taskName: string, reason: string): Promise<void> {
  await fetchJson(`${BASE_URL}/actions/${agentId}/${taskName}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

async function respondToPrompt(
  agentId: string,
  taskName: string,
  promptType: string,
  result: string,
  textInput?: string
): Promise<void> {
  const effectiveTaskName = taskName || '__prompt__'
  await fetchJson(`${BASE_URL}/actions/${agentId}/${effectiveTaskName}/respond`, {
    method: 'POST',
    body: JSON.stringify({
      prompt_type: promptType,
      result,
      text_input: textInput,
    }),
  })
}

async function submitQAAnswers(
  agentId: string,
  taskName: string,
  answers: QAAnswer[]
): Promise<void> {
  const effectiveTaskName = taskName || '__prompt__'
  await fetchJson(`${BASE_URL}/actions/${agentId}/${effectiveTaskName}/respond`, {
    method: 'POST',
    body: JSON.stringify({
      prompt_type: 'discovery_qa',
      result: 'answers',
      answers,
    }),
  })
}

async function createTask(agentId: string, request: CreateTaskRequest): Promise<void> {
  await fetchJson(`${BASE_URL}/actions/${agentId}/create-task`, {
    method: 'POST',
    body: JSON.stringify(request),
  })
}

async function getGitHubIssues(
  agentId: string,
  refresh: boolean = false
): Promise<{ issues: GitHubIssue[]; cached: boolean }> {
  return fetchJson(`${BASE_URL}/actions/${agentId}/github-issues?refresh=${refresh}`)
}

// Output
async function getOutputLines(
  agentId: string,
  since: number = 0
): Promise<{ lines: Array<{ line: string; line_type: string }>; next_index: number }> {
  return fetchJson(`${BASE_URL}/actions/${agentId}/output?since=${since}`)
}

// Export as api object for convenience
export const api = {
  getAgents,
  getAgent,
  getTasks,
  getRecentTasks,
  getEvents,
  approveTask,
  rejectTask,
  respondToPrompt,
  submitQAAnswers,
  createTask,
  getGitHubIssues,
  getOutputLines,
}

// Also export individual functions
export {
  getAgents,
  getAgent,
  getTasks,
  getRecentTasks,
  getEvents,
  approveTask,
  rejectTask,
  respondToPrompt,
  submitQAAnswers,
  createTask,
  getGitHubIssues,
  getOutputLines,
}
