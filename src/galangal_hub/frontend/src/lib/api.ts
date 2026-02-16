import type {
  AgentWithState,
  CreateTaskRequest,
  CredentialProfile,
  CredentialProfileCreate,
  DopplerStatus,
  EditorStatus,
  Environment,
  EnvironmentCreate,
  EnvironmentUpdate,
  EnvironmentWithAgent,
  GitHubIssue,
  GitStatus,
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

async function getTaskArtifacts(
  agentId: string,
  taskName: string
): Promise<{ agent_id: string; task_name: string; artifacts: Record<string, string>; count: number }> {
  return fetchJson(`${BASE_URL}/tasks/${agentId}/${encodeURIComponent(taskName)}/artifacts`)
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

// Credential Profiles
async function getCredentialProfiles(): Promise<CredentialProfile[]> {
  return fetchJson<CredentialProfile[]>(`${BASE_URL}/credentials`)
}

async function createCredentialProfile(data: CredentialProfileCreate): Promise<CredentialProfile> {
  return fetchJson<CredentialProfile>(`${BASE_URL}/credentials`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

async function updateCredentialProfile(
  profileId: string,
  data: Partial<CredentialProfileCreate>
): Promise<void> {
  await fetchJson(`${BASE_URL}/credentials/${profileId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

async function deleteCredentialProfile(profileId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/credentials/${profileId}`, { method: 'DELETE' })
}

async function testCredentialProfile(profileId: string): Promise<{ valid: boolean; provider: string; error?: string }> {
  return fetchJson(`${BASE_URL}/credentials/${profileId}/test`, { method: 'POST' })
}

// Environments
async function getEnvironments(): Promise<EnvironmentWithAgent[]> {
  return fetchJson<EnvironmentWithAgent[]>(`${BASE_URL}/environments`)
}

async function getEnvironment(envId: string): Promise<EnvironmentWithAgent> {
  return fetchJson<EnvironmentWithAgent>(`${BASE_URL}/environments/${envId}`)
}

async function createEnvironment(data: EnvironmentCreate): Promise<Environment> {
  return fetchJson<Environment>(`${BASE_URL}/environments`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

async function updateEnvironment(envId: string, data: EnvironmentUpdate): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

async function deleteEnvironment(envId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}`, { method: 'DELETE' })
}

async function startDevServer(envId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}/start`, { method: 'POST' })
}

async function stopDevServer(envId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}/stop`, { method: 'POST' })
}

async function restartDevServer(envId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}/restart`, { method: 'POST' })
}

async function getDevServerLogs(
  envId: string,
  kind: string = 'dev_server',
  limit: number = 200
): Promise<{ lines: string[]; running: boolean }> {
  return fetchJson(`${BASE_URL}/environments/${envId}/logs?kind=${kind}&limit=${limit}`)
}

async function getEnvGitStatus(envId: string): Promise<GitStatus> {
  return fetchJson<GitStatus>(`${BASE_URL}/environments/${envId}/git-status`)
}

async function pullEnvironment(
  envId: string,
  strategy: 'ff-only' | 'rebase' | 'merge' = 'ff-only',
): Promise<{ status: string; output: string }> {
  return fetchJson(`${BASE_URL}/environments/${envId}/git-pull?strategy=${strategy}`, { method: 'POST' })
}

async function gitReset(envId: string): Promise<{ status: string; output: string }> {
  return fetchJson(`${BASE_URL}/environments/${envId}/git-reset`, { method: 'POST' })
}

async function getEnvFiles(envId: string): Promise<{ files: Record<string, string> }> {
  return fetchJson(`${BASE_URL}/environments/${envId}/env-files`)
}

async function writeEnvFiles(envId: string, files: Record<string, string>): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}/env-files`, {
    method: 'POST',
    body: JSON.stringify({ files }),
  })
}

async function startEnvironmentAgent(envId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}/agent/start`, { method: 'POST' })
}

async function stopEnvironmentAgent(envId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}/agent/stop`, { method: 'POST' })
}

// Editor
async function startEditor(envId: string): Promise<{ status: string; port: number; url: string }> {
  return fetchJson(`${BASE_URL}/environments/${envId}/editor/start`, { method: 'POST' })
}

async function stopEditor(envId: string): Promise<void> {
  await fetchJson(`${BASE_URL}/environments/${envId}/editor/stop`, { method: 'POST' })
}

async function getEditorStatus(envId: string): Promise<EditorStatus> {
  return fetchJson<EditorStatus>(`${BASE_URL}/environments/${envId}/editor/status`)
}

async function isEditorAvailable(): Promise<boolean> {
  const res = await fetchJson<{ available: boolean }>(`${BASE_URL}/editor/available`)
  return res.available
}

// Doppler / Vault
async function getDopplerStatus(token?: string): Promise<DopplerStatus> {
  const params = token ? `?token=${encodeURIComponent(token)}` : ''
  return fetchJson<DopplerStatus>(`${BASE_URL}/doppler/status${params}`)
}

// Export as api object for convenience
export const api = {
  getAgents,
  getAgent,
  getTasks,
  getRecentTasks,
  getTaskArtifacts,
  getEvents,
  approveTask,
  rejectTask,
  respondToPrompt,
  submitQAAnswers,
  createTask,
  getGitHubIssues,
  getOutputLines,
  // Credentials
  getCredentialProfiles,
  createCredentialProfile,
  updateCredentialProfile,
  deleteCredentialProfile,
  testCredentialProfile,
  // Environments
  getEnvironments,
  getEnvironment,
  createEnvironment,
  updateEnvironment,
  deleteEnvironment,
  startDevServer,
  stopDevServer,
  restartDevServer,
  getDevServerLogs,
  getEnvGitStatus,
  pullEnvironment,
  gitReset,
  getEnvFiles,
  writeEnvFiles,
  startEnvironmentAgent,
  stopEnvironmentAgent,
  // Editor
  startEditor,
  stopEditor,
  getEditorStatus,
  isEditorAvailable,
  // Doppler
  getDopplerStatus,
}

// Also export individual functions
export {
  getAgents,
  getAgent,
  getTasks,
  getRecentTasks,
  getTaskArtifacts,
  getEvents,
  approveTask,
  rejectTask,
  respondToPrompt,
  submitQAAnswers,
  createTask,
  getGitHubIssues,
  getOutputLines,
  getCredentialProfiles,
  createCredentialProfile,
  updateCredentialProfile,
  deleteCredentialProfile,
  testCredentialProfile,
  getEnvironments,
  getEnvironment,
  createEnvironment,
  updateEnvironment,
  deleteEnvironment,
  startDevServer,
  stopDevServer,
  restartDevServer,
  getDevServerLogs,
  getEnvGitStatus,
  pullEnvironment,
  gitReset,
  getEnvFiles,
  writeEnvFiles,
  startEnvironmentAgent,
  stopEnvironmentAgent,
  startEditor,
  stopEditor,
  getEditorStatus,
  isEditorAvailable,
  getDopplerStatus,
}
