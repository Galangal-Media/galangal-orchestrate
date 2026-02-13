import { Github, ExternalLink } from "lucide-react"
import { GalangalLogo } from "@/components/GalangalLogo"

export function Footer() {
  return (
    <footer className="border-t border-header-border bg-header mt-auto">
      <div className="container py-6">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          {/* Brand */}
          <div className="flex items-center gap-2.5">
            <GalangalLogo size={18} />
            <span className="font-semibold text-sm text-foreground">Galangal Hub</span>
          </div>

          {/* Links */}
          <div className="flex items-center gap-6 text-sm text-muted-foreground">
            <a
              href="https://github.com/galangal-ai/galangal-orchestrate"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 hover:text-foreground transition-colors"
            >
              <Github className="w-3.5 h-3.5" />
              <span>GitHub</span>
            </a>
            <a
              href="https://github.com/galangal-ai/galangal-orchestrate#readme"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 hover:text-foreground transition-colors"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              <span>Docs</span>
            </a>
          </div>

          {/* Copyright */}
          <div className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} Galangal AI
          </div>
        </div>
      </div>
    </footer>
  )
}
