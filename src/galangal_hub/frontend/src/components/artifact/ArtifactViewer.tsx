import { useState } from "react"
import { ChevronDown, ChevronRight, FileText } from "lucide-react"
import Markdown from "react-markdown"
import { cn } from "@/lib/utils"

interface ArtifactViewerProps {
  artifacts: Record<string, string>
}

function isMarkdownFile(name: string): boolean {
  return name.toLowerCase().endsWith(".md")
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
              "transition-all duration-200 overflow-hidden",
              expanded[name] ? "max-h-[500px]" : "max-h-0"
            )}
          >
            {isMarkdownFile(name) ? (
              <div className="p-4 overflow-y-auto bg-card prose max-w-none text-foreground">
                <Markdown>{content}</Markdown>
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
