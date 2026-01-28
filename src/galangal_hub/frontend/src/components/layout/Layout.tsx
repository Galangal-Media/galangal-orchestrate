import { Outlet } from "react-router-dom"
import { Header } from "./Header"
import { Toaster } from "@/components/ui/toaster"
import { PromptModal } from "@/components/prompt/PromptModal"

export function Layout() {
  return (
    <div className="relative min-h-screen bg-background text-foreground">
      <Header />
      <main className="container py-6">
        <Outlet />
      </main>
      <Toaster />
      <PromptModal />
    </div>
  )
}
