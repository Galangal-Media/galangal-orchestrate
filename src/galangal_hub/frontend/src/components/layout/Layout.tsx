import { Outlet } from "react-router-dom"
import { Header } from "./Header"
import { Footer } from "./Footer"
import { Toaster } from "@/components/ui/toaster"
import { PromptModal } from "@/components/prompt/PromptModal"

export function Layout() {
  return (
    <div className="flex flex-col min-h-screen bg-background text-foreground">
      <Header />
      <main className="container flex-1 py-8">
        <div className="animate-fade-in">
          <Outlet />
        </div>
      </main>
      <Footer />
      <Toaster />
      <PromptModal />
    </div>
  )
}
