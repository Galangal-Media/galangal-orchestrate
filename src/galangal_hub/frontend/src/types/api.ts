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
  type: 'refresh' | 'prompt' | 'prompt_cleared' | 'output'
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
