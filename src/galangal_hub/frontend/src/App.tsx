import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Layout } from "@/components/layout/Layout"
import { Dashboard } from "@/pages/Dashboard"
import { AgentDetail } from "@/pages/AgentDetail"
import { AgentsList } from "@/pages/AgentsList"
import { TasksList } from "@/pages/TasksList"
import { TaskDetail } from "@/pages/TaskDetail"
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
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
