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
import { useWebSocket } from "@/hooks/useWebSocket"
import { useToast } from "@/hooks/useToast"
import { api } from "@/lib/api"
import type { PromptData, PromptOption } from "@/types/api"

interface ActivePrompt extends PromptData {
  agentId: string
  taskName: string
}

export function PromptModal() {
  const [activePrompt, setActivePrompt] = useState<ActivePrompt | null>(null)
  const [answers, setAnswers] = useState<Record<string, string>>({})
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

  if (!activePrompt) return null

  const isQA = activePrompt.prompt_type === "discovery_qa"

  return (
    <Dialog open={!!activePrompt} onOpenChange={() => setActivePrompt(null)}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle>Action Required</DialogTitle>
            <Badge variant="secondary">{activePrompt.agentId}</Badge>
          </div>
          <DialogDescription className="text-left whitespace-pre-wrap">
            {activePrompt.message}
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
