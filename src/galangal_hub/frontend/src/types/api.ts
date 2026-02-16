// API Types matching FastAPI models

export interface AgentInfo {
  agent_id: string
  hostname: string
  project_name: string
  project_path: string
  agent_name: string
  version?: string
  connected_at?: string
  last_seen?: string
}

export interface TaskState {
  task_name: string
  task_description?: string
  description?: string
  task_type: string
  stage: string
  branch?: string
  attempt: number
  awaiting_approval: boolean
  last_failure?: string
  started_at?: string
  stage_durations?: Record<string, number>
  github_issue?: number
  github_repo?: string
}

export interface PromptOption {
  key: string
  label: string
  result: string
  color?: string
}

export interface PromptData {
  prompt_type: string
  message: string
  options: PromptOption[]
  questions?: string[]
  artifacts: string[]
  context: Record<string, unknown>
  timestamp?: string
}

export interface AgentWithState {
  agent: AgentInfo
  task: TaskState | null
  connected: boolean
  current_prompt: PromptData | null
  artifacts: Record<string, string>
}

export interface WorkflowEvent {
  event_type: string
  timestamp: string
  agent_id: string
  task_name?: string
  data: Record<string, unknown>
}

export interface TaskRecord {
  task_name: string
  task_type: string
  started_at: string
  completed_at?: string
  final_stage?: string
  success?: boolean
  metadata?: Record<string, unknown>
}

// WebSocket message types
export interface WSMessage {
  type: 'refresh' | 'prompt' | 'prompt_cleared' | 'output' | 'env_status'
  agent_id?: string
  agent_name?: string
  task_name?: string
  message?: string
  prompt_type?: string
  prompt?: PromptData
  line?: string
  line_type?: string
}

// API response types
export interface PromptResponse {
  prompt_type: string
  result: string
  text_input?: string
}

export interface QAAnswer {
  question: string
  answer: string
}

export interface CreateTaskRequest {
  task_name?: string
  task_description?: string
  task_type?: string
  github_issue?: number
  github_repo?: string
}

export interface GitHubIssue {
  number: number
  title: string
  labels: string[]
  state: string
  author: string
}

// Environment types
export type AIProvider = 'claude' | 'openai' | 'gemini'
export type EnvironmentStatus = 'stopped' | 'cloning' | 'ready' | 'starting' | 'running' | 'error'
export type StartMode = 'shell' | 'docker_compose'

export interface CredentialProfile {
  id: string
  name: string
  provider: AIProvider
  credentials: Record<string, string>
  created_at: string
  updated_at: string
}

export interface CredentialProfileCreate {
  name: string
  provider: AIProvider
  credentials: Record<string, string>
}

export interface Environment {
  id: string
  name: string
  repo_url: string
  branch: string
  local_path: string
  status: EnvironmentStatus
  provider: AIProvider
  credential_profile_id: string | null
  env_vars: Record<string, string>
  env_files: Record<string, string>
  start_mode: StartMode
  start_command: string | null
  stop_command: string | null
  docker_compose_file: string | null
  ports: number[]
  vault: VaultConfig | null
  agent_id: string | null
  editor_port: number | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface EnvironmentWithAgent extends Environment {
  agent_connected: boolean
  agent_name: string | null
}

export interface EnvironmentCreate {
  name: string
  repo_url: string
  branch?: string
  provider?: AIProvider
  credential_profile_id?: string | null
  env_vars?: Record<string, string>
  env_files?: Record<string, string>
  start_mode?: StartMode
  start_command?: string | null
  stop_command?: string | null
  docker_compose_file?: string | null
  ports?: number[]
  vault?: VaultConfig | null
}

export interface EnvironmentUpdate {
  name?: string
  branch?: string
  provider?: AIProvider
  credential_profile_id?: string | null
  env_vars?: Record<string, string>
  env_files?: Record<string, string>
  start_mode?: StartMode
  start_command?: string | null
  stop_command?: string | null
  docker_compose_file?: string | null
  ports?: number[]
  vault?: VaultConfig | null
}

export interface GitStatus {
  branch: string
  clean: boolean
  last_commit_hash: string
  last_commit_message: string
  remote_branches: string[]
}

// Vault types
export type VaultProvider = 'doppler'

export interface DopplerSettings {
  token: string
}

export interface VaultConfig {
  enabled: boolean
  provider: VaultProvider | null
  doppler: DopplerSettings | null
}

export interface EditorStatus {
  running: boolean
  port: number | null
  url: string | null
}

export interface DopplerStatus {
  installed: boolean
  authenticated: boolean
  project: string | null
  config: string | null
}
