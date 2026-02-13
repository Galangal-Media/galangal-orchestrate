import { useState } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
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
  const [selectedIssue, setSelectedIssue] = useState<string>("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const { toast } = useToast()

  const isQA = prompt.prompt_type === "discovery_qa"
  const isIssueSelect = prompt.prompt_type === "github_issue_select"

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

  const handleIssueSelect = async () => {
    if (isSubmitting || !selectedIssue) return

    const option = prompt.options?.find(o => o.result === selectedIssue)
    if (!option) return

    setIsSubmitting(true)
    try {
      await api.respondToPrompt(agentId, taskName, prompt.prompt_type, option.result)
      toast({
        title: "Issue Selected",
        description: `Selected: #${option.key} ${option.label}`,
        variant: "success",
      })
      onResponse?.()
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
        <div className="prose prose-sm max-w-none text-foreground prose-headings:text-foreground prose-p:text-foreground prose-strong:text-foreground prose-code:text-primary prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-muted prose-pre:border prose-pre:border-border prose-a:text-primary prose-li:text-foreground">
          <Markdown remarkPlugins={[remarkGfm]}>{prompt.message}</Markdown>
        </div>

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
        ) : isIssueSelect ? (
          <div className="flex w-full gap-2">
            <Select value={selectedIssue} onValueChange={setSelectedIssue}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder="Select an issue..." />
              </SelectTrigger>
              <SelectContent className="max-h-[300px]">
                {prompt.options?.map((option) => (
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
