import { useState } from "react"
import { ChevronDown, ChevronRight, FileText } from "lucide-react"
import Markdown, { type Components } from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

interface ArtifactViewerProps {
  artifacts: Record<string, string>
}

function isMarkdownFile(name: string): boolean {
  return name.toLowerCase().endsWith(".md")
}

const markdownComponents: Components = {
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto">
      <table className="w-full min-w-[480px] border-collapse border border-border text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/60">{children}</thead>,
  th: ({ children }) => (
    <th className="border border-border px-3 py-2 text-left font-semibold text-foreground">{children}</th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-3 py-2 align-top text-muted-foreground">{children}</td>
  ),
}

export function ArtifactViewer({ artifacts }: ArtifactViewerProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const toggleExpand = (name: string) => {
    setExpanded((prev) => ({
      ...prev,
      [name]: !prev[name],
    }))
  }

  const artifactEntries = Object.entries(artifacts)

  if (artifactEntries.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <p>No artifacts available</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {artifactEntries.map(([name, content]) => (
        <div key={name} className="border border-border rounded-lg overflow-hidden">
          <button
            onClick={() => toggleExpand(name)}
            className="w-full flex items-center gap-2 p-3 bg-muted/50 hover:bg-muted transition-colors text-left"
          >
            {expanded[name] ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            <FileText className="h-4 w-4 text-primary" />
            <span className="font-medium">{name}</span>
            <span className="text-xs text-muted-foreground ml-auto">
              {content.split("\n").length} lines
            </span>
          </button>
          <div
            className={cn(
              "transition-all duration-200",
              expanded[name] ? "max-h-[600px] overflow-y-auto" : "max-h-0 overflow-hidden"
            )}
          >
            {isMarkdownFile(name) ? (
              <div className="p-4 bg-card prose max-w-none text-foreground">
                <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {content}
                </Markdown>
              </div>
            ) : (
              <pre className="p-4 text-sm overflow-x-auto bg-card">
                <code>{content}</code>
              </pre>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
