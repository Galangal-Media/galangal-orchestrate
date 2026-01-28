import { Sparkles, Github, ExternalLink } from "lucide-react"

export function Footer() {
  return (
    <footer className="border-t border-header-border bg-header mt-auto">
      <div className="container py-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-purple-400">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            <span className="font-semibold text-foreground">Galangal Hub</span>
          </div>

          {/* Links */}
          <div className="flex items-center gap-6 text-sm text-muted-foreground">
            <a
              href="https://github.com/galangal-ai/galangal-orchestrate"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 hover:text-foreground transition-colors"
            >
              <Github className="w-4 h-4" />
              <span>GitHub</span>
            </a>
            <a
              href="https://github.com/galangal-ai/galangal-orchestrate#readme"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 hover:text-foreground transition-colors"
            >
              <ExternalLink className="w-4 h-4" />
              <span>Documentation</span>
            </a>
          </div>

          {/* Copyright */}
          <div className="text-sm text-muted-foreground">
            &copy; {new Date().getFullYear()} Galangal AI
          </div>
        </div>
      </div>
    </footer>
  )
}
