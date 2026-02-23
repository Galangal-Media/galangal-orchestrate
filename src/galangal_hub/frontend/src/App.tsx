import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Layout } from "@/components/layout/Layout"
import { Dashboard } from "@/pages/Dashboard"
import { AgentDetail } from "@/pages/AgentDetail"
import { AgentsList } from "@/pages/AgentsList"
import { TasksList } from "@/pages/TasksList"
import { TaskDetail } from "@/pages/TaskDetail"
import { EnvironmentsList } from "@/pages/EnvironmentsList"
import { EnvironmentDetail } from "@/pages/EnvironmentDetail"
import { AIKeysList } from "@/pages/AIKeysList"
import { ProfilesList } from "@/pages/ProfilesList"
import { useTheme } from "@/hooks/useTheme"
import { useEffect } from "react"

function App() {
  const { theme } = useTheme()

  // Apply theme class to document
  useEffect(() => {
    const root = document.documentElement
    root.classList.remove("light", "dark")
    root.classList.add(theme)
  }, [theme])

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/agents" element={<AgentsList />} />
          <Route path="/agents/:agentId" element={<AgentDetail />} />
          <Route path="/agents/:agentId/tasks/:taskName" element={<TaskDetail />} />
          <Route path="/tasks" element={<TasksList />} />
          <Route path="/environments" element={<EnvironmentsList />} />
          <Route path="/environments/:envId" element={<EnvironmentDetail />} />
          <Route path="/ai-keys" element={<AIKeysList />} />
          <Route path="/profiles" element={<ProfilesList />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
