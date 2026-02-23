import { useEffect, useState, useCallback } from "react"
import { api } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Save, ToggleLeft, ToggleRight, Plus, X, AlertCircle, Check } from "lucide-react"

interface ConfigEditorProps {
  envId: string
}

export function ConfigEditor({ envId }: ConfigEditorProps) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState<"form" | "yaml">("form")
  const [rawYaml, setRawYaml] = useState("")
  const [config, setConfig] = useState<Record<string, unknown>>({})
  const [exists, setExists] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  const fetchConfig = useCallback(async () => {
    try {
      const data = await api.getGalangalConfig(envId)
      setConfig(data.config || {})
      setRawYaml(data.raw || "")
      setExists(data.exists)
      if (data.error) setError(data.error)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load config")
    } finally {
      setLoading(false)
    }
  }, [envId])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    setSuccess(false)
    setValidationError(null)
    try {
      if (mode === "yaml") {
        await api.updateGalangalConfig(envId, { raw: rawYaml })
      } else {
        await api.updateGalangalConfig(envId, { config })
      }
      setSuccess(true)
      setTimeout(() => setSuccess(false), 3000)
      fetchConfig()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save config")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent mx-auto mt-8" />
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Galangal Config</CardTitle>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setMode(mode === "form" ? "yaml" : "form")}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {mode === "form" ? (
                <>
                  <ToggleLeft className="h-4 w-4" />
                  Switch to YAML
                </>
              ) : (
                <>
                  <ToggleRight className="h-4 w-4" />
                  Switch to Form
                </>
              )}
            </button>
          </div>
        </div>
        {!exists && (
          <p className="text-xs text-muted-foreground">
            No .galangal/config.yaml found. Save to create one.
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <div className="px-3 py-2 bg-destructive/10 border border-destructive/40 rounded text-destructive text-sm flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
            <button onClick={() => setError(null)} className="ml-auto underline text-xs">dismiss</button>
          </div>
        )}

        {success && (
          <div className="px-3 py-2 bg-success/10 border border-success/40 rounded text-success text-sm flex items-center gap-2">
            <Check className="h-4 w-4 shrink-0" />
            Config saved successfully.
          </div>
        )}

        {mode === "yaml" ? (
          <YamlEditor
            value={rawYaml}
            onChange={setRawYaml}
            validationError={validationError}
          />
        ) : (
          <FormEditor config={config} onChange={setConfig} />
        )}

        <div className="flex justify-end pt-2">
          <Button onClick={handleSave} disabled={saving} size="sm" className="gap-1.5">
            <Save className="h-3.5 w-3.5" />
            {saving ? "Saving..." : "Save"}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function YamlEditor({
  value,
  onChange,
  validationError,
}: {
  value: string
  onChange: (v: string) => void
  validationError: string | null
}) {
  return (
    <div className="space-y-2">
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="font-mono text-xs min-h-[400px] leading-relaxed"
        placeholder="# .galangal/config.yaml"
      />
      {validationError && (
        <p className="text-xs text-destructive">{validationError}</p>
      )}
    </div>
  )
}

function FormEditor({
  config,
  onChange,
}: {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
}) {
  // Helper to get nested values
  const get = (path: string, defaultVal: unknown = "") => {
    const parts = path.split(".")
    let current: unknown = config
    for (const part of parts) {
      if (current == null || typeof current !== "object") return defaultVal
      current = (current as Record<string, unknown>)[part]
    }
    return current ?? defaultVal
  }

  // Helper to set nested values
  const set = (path: string, value: unknown) => {
    const parts = path.split(".")
    const newConfig = JSON.parse(JSON.stringify(config))
    let current = newConfig
    for (let i = 0; i < parts.length - 1; i++) {
      if (current[parts[i]] == null || typeof current[parts[i]] !== "object") {
        current[parts[i]] = {}
      }
      current = current[parts[i]]
    }
    current[parts[parts.length - 1]] = value
    onChange(newConfig)
  }

  const skipStages = (get("stages.skip", []) as string[]) || []
  const testSuites = (get("test_gate.test_suites", []) as string[]) || []
  const peerStages = (get("peer_review.stages", []) as string[]) || []

  return (
    <div className="space-y-6">
      {/* Project */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Project</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs font-medium">Name</label>
            <Input
              value={get("project.name") as string}
              onChange={(e) => set("project.name", e.target.value)}
              placeholder="my-project"
              className="text-sm"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium">Approver</label>
            <Input
              value={get("project.approver") as string}
              onChange={(e) => set("project.approver", e.target.value)}
              placeholder="auto"
              className="text-sm"
            />
          </div>
        </div>
      </section>

      {/* Stages */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Stages</h3>
        <div className="grid grid-cols-3 gap-3">
          <div className="space-y-1">
            <label className="text-xs font-medium">Default Timeout (s)</label>
            <Input
              type="number"
              value={get("stages.timeout", "") as string}
              onChange={(e) => set("stages.timeout", e.target.value ? Number(e.target.value) : undefined)}
              placeholder="300"
              className="text-sm"
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium">Max Retries</label>
            <Input
              type="number"
              value={get("stages.max_retries", "") as string}
              onChange={(e) => set("stages.max_retries", e.target.value ? Number(e.target.value) : undefined)}
              placeholder="2"
              className="text-sm"
            />
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium">Skip Stages</label>
          <StringListEditor
            values={skipStages}
            onChange={(v) => set("stages.skip", v)}
            placeholder="e.g. BENCHMARK"
          />
        </div>
      </section>

      {/* AI */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">AI</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs font-medium">Default Backend</label>
            <Select
              value={(get("ai.default_backend") as string) || "__none__"}
              onValueChange={(v) => set("ai.default_backend", v === "__none__" ? undefined : v)}
            >
              <SelectTrigger className="text-sm">
                <SelectValue placeholder="Default" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">Default</SelectItem>
                <SelectItem value="claude">Claude</SelectItem>
                <SelectItem value="codex">Codex</SelectItem>
                <SelectItem value="gemini">Gemini</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </section>

      {/* Peer Review */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Peer Review</h3>
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="peer-review-enabled"
            checked={!!get("peer_review.enabled")}
            onChange={(e) => set("peer_review.enabled", e.target.checked)}
            className="rounded border-border"
          />
          <label htmlFor="peer-review-enabled" className="text-xs font-medium">
            Enable peer review
          </label>
        </div>
        {!!get("peer_review.enabled") && (
          <div className="space-y-3 pl-6">
            <div className="space-y-1">
              <label className="text-xs font-medium">Backend</label>
              <Select
                value={(get("peer_review.backend") as string) || "__none__"}
                onValueChange={(v) => set("peer_review.backend", v === "__none__" ? undefined : v)}
              >
                <SelectTrigger className="text-sm">
                  <SelectValue placeholder="Select" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Default</SelectItem>
                  <SelectItem value="codex">Codex</SelectItem>
                  <SelectItem value="claude">Claude</SelectItem>
                  <SelectItem value="gemini">Gemini</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium">Stages</label>
              <StringListEditor
                values={peerStages}
                onChange={(v) => set("peer_review.stages", v)}
                placeholder="e.g. DEV"
              />
            </div>
          </div>
        )}
      </section>

      {/* Test Gate */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Test Gate</h3>
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="test-gate-enabled"
            checked={!!get("test_gate.enabled")}
            onChange={(e) => set("test_gate.enabled", e.target.checked)}
            className="rounded border-border"
          />
          <label htmlFor="test-gate-enabled" className="text-xs font-medium">
            Enable test gate
          </label>
        </div>
        {!!get("test_gate.enabled") && (
          <div className="space-y-1 pl-6">
            <label className="text-xs font-medium">Test Suites</label>
            <StringListEditor
              values={testSuites}
              onChange={(v) => set("test_gate.test_suites", v)}
              placeholder="e.g. pytest tests/"
            />
          </div>
        )}
      </section>

      {/* PR */}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Pull Request</h3>
        <div className="space-y-1">
          <label className="text-xs font-medium">Base Branch</label>
          <Input
            value={get("pr.base_branch") as string}
            onChange={(e) => set("pr.base_branch", e.target.value)}
            placeholder="main"
            className="text-sm w-48"
          />
        </div>
      </section>
    </div>
  )
}

function StringListEditor({
  values,
  onChange,
  placeholder,
}: {
  values: string[]
  onChange: (v: string[]) => void
  placeholder: string
}) {
  const [newItem, setNewItem] = useState("")

  const add = () => {
    if (newItem.trim() && !values.includes(newItem.trim())) {
      onChange([...values, newItem.trim()])
      setNewItem("")
    }
  }

  const remove = (i: number) => {
    onChange(values.filter((_, idx) => idx !== i))
  }

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5">
        {values.map((v, i) => (
          <span key={i} className="inline-flex items-center gap-1 bg-muted px-2 py-0.5 rounded text-xs font-mono">
            {v}
            <button onClick={() => remove(i)} className="text-muted-foreground hover:text-foreground">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        <Input
          value={newItem}
          onChange={(e) => setNewItem(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
          placeholder={placeholder}
          className="text-xs h-7 w-40"
        />
        <Button size="sm" variant="ghost" onClick={add} className="h-7 px-2" disabled={!newItem.trim()}>
          <Plus className="h-3 w-3" />
        </Button>
      </div>
    </div>
  )
}
