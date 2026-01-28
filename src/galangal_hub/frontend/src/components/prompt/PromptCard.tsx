import { useState } from "react"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { useToast } from "@/hooks/useToast"
import { api } from "@/lib/api"
import type { PromptData, PromptOption } from "@/types/api"
import { AlertCircle } from "lucide-react"

interface PromptCardProps {
  prompt: PromptData
  agentId: string
  taskName: string
  onResponse?: () => void
}

export function PromptCard({ prompt, agentId, taskName, onResponse }: PromptCardProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const { toast } = useToast()

  const isQA = prompt.prompt_type === "discovery_qa"

  const handleOptionClick = async (option: PromptOption) => {
    if (isSubmitting) return

    setIsSubmitting(true)
    try {
      await api.respondToPrompt(agentId, taskName, prompt.prompt_type, option.result)
      toast({
        title: "Response Sent",
        description: `Selected: ${option.label}`,
        variant: "success",
      })
      onResponse?.()
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
    if (isSubmitting) return

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
      await api.submitQAAnswers(agentId, taskName, answersArray)
      toast({
        title: "Answers Submitted",
        description: `Submitted ${answersArray.length} answer(s)`,
        variant: "success",
      })
      onResponse?.()
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

  return (
    <Card className="border-warning/50 bg-warning/5">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-warning" />
          <CardTitle className="text-warning">Action Required</CardTitle>
          <Badge variant="outline" className="ml-auto">
            {prompt.prompt_type}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm whitespace-pre-wrap">{prompt.message}</p>

        {isQA && prompt.questions && (
          <div className="space-y-4">
            {prompt.questions.map((question, index) => (
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
      </CardContent>
      <CardFooter className="flex flex-wrap gap-2">
        {isQA ? (
          <Button
            variant="success"
            onClick={handleQASubmit}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Submitting..." : "Submit Answers"}
          </Button>
        ) : (
          prompt.options?.map((option) => (
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
      </CardFooter>
    </Card>
  )
}
