import { useEffect, useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useWebSocket } from "@/hooks/useWebSocket"
import { useToast } from "@/hooks/useToast"
import { api } from "@/lib/api"
import type { PromptData, PromptOption } from "@/types/api"

// Convert URLs in text to clickable links
function linkifyText(text: string): React.ReactNode[] {
  const urlRegex = /(https?:\/\/[^\s]+)/g
  const parts = text.split(urlRegex)

  return parts.map((part, index) => {
    if (urlRegex.test(part)) {
      urlRegex.lastIndex = 0
      return (
        <a
          key={index}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline hover:text-primary/80"
        >
          {part}
        </a>
      )
    }
    return part
  })
}

interface ActivePrompt extends PromptData {
  agentId: string
  taskName: string
}

export function PromptModal() {
  const [activePrompt, setActivePrompt] = useState<ActivePrompt | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [selectedIssue, setSelectedIssue] = useState<string>("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const { toast } = useToast()

  const { lastMessage } = useWebSocket("/ws/dashboard")

  useEffect(() => {
    if (!lastMessage) return

    try {
      const data = JSON.parse(lastMessage)
      if (data.type === "prompt" && data.prompt) {
        setActivePrompt({
          ...data.prompt,
          agentId: data.agent_id,
          taskName: data.task_name,
        })
        setAnswers({})
        toast({
          title: "New Prompt",
          description: `${data.agent_id}: ${data.prompt.message.substring(0, 50)}...`,
          variant: "warning",
        })
      } else if (data.type === "prompt_cleared") {
        if (activePrompt?.agentId === data.agent_id) {
          setActivePrompt(null)
        }
      }
    } catch {
      // Ignore non-JSON messages
    }
  }, [lastMessage, toast, activePrompt?.agentId])

  const handleOptionClick = async (option: PromptOption) => {
    if (!activePrompt || isSubmitting) return

    setIsSubmitting(true)
    try {
      await api.respondToPrompt(
        activePrompt.agentId,
        activePrompt.taskName,
        activePrompt.prompt_type,
        option.result
      )
      setActivePrompt(null)
      toast({
        title: "Response Sent",
        description: `Selected: ${option.label}`,
        variant: "success",
      })
    } catch (error) {
      toast({
        title: "Error",
        description: error instanceof Error ? error.message : "Failed to send response",
        variant: "destructive",
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleQASubmit = async () => {
    if (!activePrompt || isSubmitting) return

    const answersArray = Object.entries(answers)
      .filter(([_, value]) => value.trim())
      .map(([key, value]) => ({ question: key, answer: value }))

    if (answersArray.length === 0) {
      toast({
        title: "No Answers",
        description: "Please provide at least one answer",
        variant: "warning",
      })
      return
    }

    setIsSubmitting(true)
    try {
      await api.submitQAAnswers(
        activePrompt.agentId,
        activePrompt.taskName,
        answersArray
      )
      setActivePrompt(null)
      setAnswers({})
      toast({
        title: "Answers Submitted",
        description: `Submitted ${answersArray.length} answer(s)`,
        variant: "success",
      })
    } catch (error) {
      toast({
        title: "Error",
        description: error instanceof Error ? error.message : "Failed to submit answers",
        variant: "destructive",
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleIssueSelect = async () => {
    if (!activePrompt || isSubmitting || !selectedIssue) return

    const option = activePrompt.options?.find(o => o.result === selectedIssue)
    if (!option) return

    setIsSubmitting(true)
    try {
      await api.respondToPrompt(
        activePrompt.agentId,
        activePrompt.taskName,
        activePrompt.prompt_type,
        option.result
      )
      setActivePrompt(null)
      setSelectedIssue("")
      toast({
        title: "Issue Selected",
        description: `Selected: #${option.key} ${option.label}`,
        variant: "success",
      })
    } catch (error) {
      toast({
        title: "Error",
        description: error instanceof Error ? error.message : "Failed to select issue",
        variant: "destructive",
      })
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!activePrompt) return null

  const isQA = activePrompt.prompt_type === "discovery_qa"
  const isIssueSelect = activePrompt.prompt_type === "github_issue_select"

  return (
    <Dialog open={!!activePrompt} onOpenChange={() => setActivePrompt(null)}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle>Action Required</DialogTitle>
            <Badge variant="secondary">{activePrompt.agentId}</Badge>
          </div>
          <DialogDescription className="text-left whitespace-pre-wrap">
            {linkifyText(activePrompt.message)}
          </DialogDescription>
        </DialogHeader>

        {isQA && activePrompt.questions && (
          <div className="space-y-4 py-4">
            {activePrompt.questions.map((question, index) => (
              <div key={index} className="space-y-2">
                <label className="text-sm font-medium">
                  {index + 1}. {question}
                </label>
                <Textarea
                  value={answers[question] || ""}
                  onChange={(e) =>
                    setAnswers((prev) => ({
                      ...prev,
                      [question]: e.target.value,
                    }))
                  }
                  placeholder="Your answer..."
                  rows={2}
                />
              </div>
            ))}
          </div>
        )}

        <DialogFooter className="flex-col sm:flex-row gap-2">
          {isQA ? (
            <>
              <Button
                variant="outline"
                onClick={() => setActivePrompt(null)}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button
                variant="success"
                onClick={handleQASubmit}
                disabled={isSubmitting}
              >
                {isSubmitting ? "Submitting..." : "Submit Answers"}
              </Button>
            </>
          ) : isIssueSelect ? (
            <div className="flex w-full gap-2">
              <Select value={selectedIssue} onValueChange={setSelectedIssue}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Select an issue..." />
                </SelectTrigger>
                <SelectContent className="max-h-[300px]">
                  {activePrompt.options?.map((option) => (
                    <SelectItem key={option.key} value={option.result}>
                      #{option.key} {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="success"
                onClick={handleIssueSelect}
                disabled={isSubmitting || !selectedIssue}
              >
                {isSubmitting ? "Selecting..." : "Select"}
              </Button>
            </div>
          ) : (
            activePrompt.options?.map((option) => (
              <Button
                key={option.key}
                variant={
                  option.result === "yes" || option.result === "approve"
                    ? "success"
                    : option.result === "no" || option.result === "reject"
                    ? "destructive"
                    : "secondary"
                }
                onClick={() => handleOptionClick(option)}
                disabled={isSubmitting}
              >
                {option.key}. {option.label}
              </Button>
            ))
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
