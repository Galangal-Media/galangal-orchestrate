import { AgentCard } from "./AgentCard"
import type { AgentInfo, TaskState, PromptData } from "@/types/api"

interface AgentWithState {
  agent: AgentInfo
  task?: TaskState | null
  prompt?: PromptData | null
  connected?: boolean
}

interface AgentListProps {
  agents: AgentWithState[]
  emptyMessage?: string
}

export function AgentList({ agents, emptyMessage = "No agents connected" }: AgentListProps) {
  if (agents.length === 0) {
    return (
      <div className="text-center py-16 px-4 rounded-xl border border-dashed border-border bg-card/50">
        <p className="text-muted-foreground">{emptyMessage}</p>
      </div>
    )
  }

  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
      {agents.map((item) => (
        <AgentCard
          key={item.agent.agent_id}
          agent={item.agent}
          task={item.task}
          prompt={item.prompt}
          connected={item.connected}
        />
      ))}
    </div>
  )
}
