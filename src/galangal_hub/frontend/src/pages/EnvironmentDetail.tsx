import { useEffect, useState, useCallback, useRef } from "react"
import { useParams, useNavigate, Link } from "react-router-dom"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type {
  EnvironmentWithAgent,
  EnvironmentUpdate,
  CredentialProfile,
  GitStatus,
  EditorStatus,
  AIProvider,
  StartMode,
  WSMessage,
  VaultProvider,
} from "@/types/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
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
import {
  Play,
  Square,
  RotateCcw,
  Trash2,
  Bot,
  GitBranch,
  ArrowDownToLine,
  Plus,
  X,
  Save,
  Code2,
  ExternalLink,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { DopplerConnect, type DopplerSelection } from "@/components/vault/DopplerConnect"
import Ansi from "ansi-to-react"

const statusVariant: Record<string, "default" | "secondary" | "destructive" | "success" | "warning"> = {
  stopped: "secondary",
  cloning: "warning",
  ready: "warning",
  starting: "warning",
  running: "success",
  error: "destructive",
}

type Tab = "config" | "env_vars" | "env_files" | "git" | "logs" | "agent" | "editor"

export function EnvironmentDetail() {
  const { envId } = useParams<{ envId: string }>()
  const navigate = useNavigate()
  const [env, setEnv] = useState<EnvironmentWithAgent | null>(null)
  const [credentials, setCredentials] = useState<CredentialProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>("config")
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [pullDiverged, setPullDiverged] = useState(false)

  const { lastMessage } = useWebSocket("/ws/dashboard")

  const fetchEnv = useCallback(async () => {
    if (!envId) return
    try {
      const [envData, creds] = await Promise.all([
        api.getEnvironment(envId),
        api.getCredentialProfiles(),
      ])
      setEnv(envData)
      setCredentials(creds)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch environment")
    } finally {
      setLoading(false)
    }
  }, [envId])

  useEffect(() => {
    fetchEnv()
  }, [fetchEnv])

  useEffect(() => {
    if (lastMessage) {
      try {
        const msg: WSMessage = JSON.parse(lastMessage)
        if (msg.type === "env_status" || msg.type === "refresh") {
          fetchEnv()
        }
      } catch {
        // ignore
      }
    }
  }, [lastMessage, fetchEnv])

  const doAction = async (name: string, fn: () => Promise<void>) => {
    setActionLoading(name)
    try {
      await fn()
      fetchEnv()
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to ${name}`)
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async () => {
    if (!envId || !confirm("Delete this environment? This will remove all files.")) return
    await doAction("delete", async () => {
      await api.deleteEnvironment(envId)
      navigate("/environments")
    })
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (!env) {
    return <div className="text-center py-16 text-muted-foreground">Environment not found</div>
  }

  const canStart = ["ready", "stopped", "error"].includes(env.status)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{env.name}</h1>
          <div className="flex items-center gap-2 mt-1.5 text-sm text-muted-foreground">
            <GitBranch className="h-3.5 w-3.5" />
            <span>{env.branch}</span>
            <span className="mx-1">-</span>
            <span className="truncate max-w-xs">{env.repo_url}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={statusVariant[env.status] || "secondary"}>{env.status}</Badge>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 underline text-xs">dismiss</button>
        </div>
      )}

      {env.error_message && (
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {env.error_message}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => doAction("start", () => api.startDevServer(env.id))}
          disabled={!!actionLoading || !canStart}
          className="gap-1.5"
        >
          <Play className="h-3.5 w-3.5" />
          {actionLoading === "start" ? "Starting..." : "Start Server"}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => doAction("stop", () => api.stopDevServer(env.id))}
          disabled={!!actionLoading}
          className="gap-1.5"
        >
          <Square className="h-3.5 w-3.5" />
          {actionLoading === "stop" ? "Stopping..." : "Stop Server"}
        </Button>
        {env.status === "running" && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => doAction("restart", () => api.restartDevServer(env.id))}
            disabled={!!actionLoading}
            className="gap-1.5"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Restart
          </Button>
        )}
        {!env.agent_connected ? (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => doAction("agent_start", () => api.startEnvironmentAgent(env.id))}
            disabled={!!actionLoading || env.status === "cloning"}
            className="gap-1.5"
          >
            <Bot className="h-3.5 w-3.5" />
            Start Agent
          </Button>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => doAction("agent_stop", () => api.stopEnvironmentAgent(env.id))}
            disabled={!!actionLoading}
            className="gap-1.5"
          >
            <Bot className="h-3.5 w-3.5" />
            Stop Agent
          </Button>
        )}
        <Button
          size="sm"
          variant="secondary"
          onClick={() => doAction("editor_start", () => api.startEditor(env.id).then(() => { setActiveTab("editor") }))}
          disabled={!!actionLoading || env.status === "cloning"}
          className="gap-1.5"
        >
          <Code2 className="h-3.5 w-3.5" />
          {actionLoading === "editor_start" ? "Starting..." : "Editor"}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            setActionLoading("pull")
            try {
              await api.pullEnvironment(env.id)
              fetchEnv()
            } catch (err) {
              const msg = err instanceof Error ? err.message : ""
              if (msg.includes("diverged") || msg.includes("rebase or merge")) {
                setPullDiverged(true)
                setActiveTab("git")
              } else {
                setError(msg || "Failed to pull")
              }
            } finally {
              setActionLoading(null)
            }
          }}
          disabled={!!actionLoading || env.status === "cloning"}
          className="gap-1.5"
        >
          <ArrowDownToLine className="h-3.5 w-3.5" />
          Pull
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={handleDelete}
          disabled={!!actionLoading}
          className="gap-1.5 text-destructive hover:text-destructive"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </Button>
      </div>

      {/* Tabs */}
      <div className="border-b border-border">
        <nav className="flex gap-0.5 -mb-px">
          {(["config", "env_vars", "env_files", "git", "logs", "agent", "editor"] as Tab[]).map((tab) => {
            const label = tab === "env_vars" ? "Env Vars" : tab === "env_files" ? "Env Files" : tab.charAt(0).toUpperCase() + tab.slice(1)
            return (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  "px-3.5 py-2 text-sm font-medium border-b-2 transition-colors",
                  activeTab === tab
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30"
                )}
              >
                {label}
              </button>
            )
          })}
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === "config" && (
        <ConfigTab env={env} credentials={credentials} onSaved={fetchEnv} />
      )}
      {activeTab === "env_vars" && (
        <EnvVarsTab env={env} onSaved={fetchEnv} />
      )}
      {activeTab === "env_files" && (
        <EnvFilesTab env={env} />
      )}
      {activeTab === "git" && (
        <GitTab env={env} initialDiverged={pullDiverged} onDivergedHandled={() => setPullDiverged(false)} />
      )}
      {activeTab === "logs" && (
        <LogsTab envId={env.id} />
      )}
      {activeTab === "agent" && (
        <AgentTab env={env} />
      )}
      {activeTab === "editor" && (
        <EditorTab envId={env.id} />
      )}
    </div>
  )
}

// --- Config Tab ---
function ConfigTab({
  env,
  credentials,
  onSaved,
}: {
  env: EnvironmentWithAgent
  credentials: CredentialProfile[]
  onSaved: () => void
}) {
  const [name, setName] = useState(env.name)
  const [branch, setBranch] = useState(env.branch)
  const [provider, setProvider] = useState<AIProvider>(env.provider)
  const [credentialId, setCredentialId] = useState(env.credential_profile_id || "__none__")
  const [startMode, setStartMode] = useState<StartMode>(env.start_mode)
  const [startCommand, setStartCommand] = useState(env.start_command || "")
  const [stopCommand, setStopCommand] = useState(env.stop_command || "")
  const [composeFile, setComposeFile] = useState(env.docker_compose_file || "")
  const [saving, setSaving] = useState(false)

  // Vault state
  const [vaultEnabled, setVaultEnabled] = useState(env.vault?.enabled || false)
  const [vaultProvider, setVaultProvider] = useState<VaultProvider | "">(env.vault?.provider || "")
  const [dopplerSelection, setDopplerSelection] = useState<DopplerSelection | null>(
    env.vault?.doppler?.token ? { token: env.vault.doppler.token } : null
  )

  const dopplerInitial = env.vault?.doppler?.token
    ? { token: env.vault.doppler.token }
    : undefined

  const buildVaultConfig = () => {
    if (!vaultEnabled || vaultProvider !== "doppler" || !dopplerSelection) {
      return { enabled: false, provider: null, doppler: null }
    }
    return {
      enabled: true,
      provider: "doppler" as VaultProvider,
      doppler: dopplerSelection,
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const update: EnvironmentUpdate = {
        name: name !== env.name ? name : undefined,
        branch: branch !== env.branch ? branch : undefined,
        provider,
        credential_profile_id: credentialId !== "__none__" ? credentialId : undefined,
        start_mode: startMode,
        start_command: startMode === "shell" ? startCommand : null,
        stop_command: startMode === "shell" ? stopCommand : null,
        docker_compose_file: startMode === "docker_compose" ? composeFile || undefined : undefined,
        vault: buildVaultConfig(),
      }
      await api.updateEnvironment(env.id, update)
      onSaved()
    } catch {
      // error handled elsewhere
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label className="text-sm font-medium">Name</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Repository</label>
            <Input value={env.repo_url} disabled />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Branch</label>
            <Input value={branch} onChange={(e) => setBranch(e.target.value)} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">AI Provider</label>
            <Select value={provider} onValueChange={(v) => setProvider(v as AIProvider)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="claude">Claude</SelectItem>
                <SelectItem value="openai">OpenAI</SelectItem>
                <SelectItem value="gemini">Gemini</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Credential Profile</label>
            <Select value={credentialId} onValueChange={setCredentialId}>
              <SelectTrigger>
                <SelectValue placeholder="None" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__">None</SelectItem>
                {credentials
                  .filter((c) => c.provider === provider)
                  .map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Third-party Vault */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="vault-config-enabled"
              checked={vaultEnabled}
              onChange={(e) => setVaultEnabled(e.target.checked)}
              className="rounded border-border"
            />
            <label htmlFor="vault-config-enabled" className="text-sm font-medium">
              Use third-party vault for secrets
            </label>
          </div>
          {vaultEnabled && (
            <div className="space-y-3 pl-6">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Provider</label>
                <Select value={vaultProvider} onValueChange={(v) => setVaultProvider(v as VaultProvider)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select provider" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="doppler">Doppler</SelectItem>
                    <SelectItem value="__coming_soon__" disabled>More coming soon</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {vaultProvider === "doppler" && (
                <DopplerConnect
                  initial={dopplerInitial}
                  onChange={setDopplerSelection}
                />
              )}
            </div>
          )}
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium">Start Mode</label>
          <Select value={startMode} onValueChange={(v) => setStartMode(v as StartMode)}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="docker_compose">Docker Compose</SelectItem>
              <SelectItem value="shell">Shell Command</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {startMode === "shell" && (
          <>
            <div className="space-y-2">
              <label className="text-sm font-medium">Start Command</label>
              <Input
                value={startCommand}
                onChange={(e) => setStartCommand(e.target.value)}
                placeholder="npm run dev"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Stop Command</label>
              <Input
                value={stopCommand}
                onChange={(e) => setStopCommand(e.target.value)}
                placeholder="npm run stop (optional)"
              />
              <p className="text-xs text-muted-foreground">
                Runs before terminating the process. Leave empty to just kill the process.
              </p>
            </div>
          </>
        )}

        {startMode === "docker_compose" && (
          <div className="space-y-2">
            <label className="text-sm font-medium">Compose File</label>
            <Input
              value={composeFile}
              onChange={(e) => setComposeFile(e.target.value)}
              placeholder="docker-compose.yml"
            />
          </div>
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

// --- Env Vars Tab ---
function EnvVarsTab({ env, onSaved }: { env: EnvironmentWithAgent; onSaved: () => void }) {
  const [vars, setVars] = useState<Array<{ key: string; value: string }>>(
    Object.entries(env.env_vars).map(([key, value]) => ({ key, value }))
  )
  const [saving, setSaving] = useState(false)

  const addVar = () => setVars([...vars, { key: "", value: "" }])
  const removeVar = (i: number) => setVars(vars.filter((_, idx) => idx !== i))

  const handleSave = async () => {
    setSaving(true)
    try {
      const envVars: Record<string, string> = {}
      for (const v of vars) {
        if (v.key.trim()) envVars[v.key.trim()] = v.value
      }
      await api.updateEnvironment(env.id, { env_vars: envVars })
      onSaved()
    } catch {
      // error handled elsewhere
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Environment Variables</CardTitle>
          <Button size="sm" variant="ghost" onClick={addVar} className="gap-1">
            <Plus className="h-3.5 w-3.5" />
            Add
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {vars.length === 0 ? (
          <p className="text-sm text-muted-foreground">No environment variables configured.</p>
        ) : (
          vars.map((v, i) => (
            <div key={i} className="flex gap-2 items-center">
              <Input
                value={v.key}
                onChange={(e) => {
                  const updated = [...vars]
                  updated[i] = { ...v, key: e.target.value }
                  setVars(updated)
                }}
                placeholder="KEY"
                className="font-mono text-xs w-40"
              />
              <span className="text-muted-foreground">=</span>
              <Input
                value={v.value}
                onChange={(e) => {
                  const updated = [...vars]
                  updated[i] = { ...v, value: e.target.value }
                  setVars(updated)
                }}
                placeholder="value"
                className="font-mono text-xs flex-1"
              />
              <Button size="icon" variant="ghost" onClick={() => removeVar(i)} className="shrink-0 h-8 w-8">
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))
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

// --- Env Files Tab ---
function EnvFilesTab({ env }: { env: EnvironmentWithAgent }) {
  const [files, setFiles] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [newFileName, setNewFileName] = useState("")

  useEffect(() => {
    api.getEnvFiles(env.id).then((data) => {
      setFiles(data.files)
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [env.id])

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.writeEnvFiles(env.id, files)
    } catch {
      // error handled elsewhere
    } finally {
      setSaving(false)
    }
  }

  const addFile = () => {
    if (newFileName.trim()) {
      setFiles({ ...files, [newFileName.trim()]: "" })
      setNewFileName("")
    }
  }

  const removeFile = (name: string) => {
    const updated = { ...files }
    delete updated[name]
    setFiles(updated)
  }

  if (loading) {
    return <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent mx-auto mt-8" />
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Environment Files</CardTitle>
          <div className="flex gap-2">
            <Input
              value={newFileName}
              onChange={(e) => setNewFileName(e.target.value)}
              placeholder=".env"
              className="w-32 text-xs"
              onKeyDown={(e) => e.key === "Enter" && addFile()}
            />
            <Button size="sm" variant="ghost" onClick={addFile} className="gap-1" disabled={!newFileName.trim()}>
              <Plus className="h-3.5 w-3.5" />
              Add
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {Object.keys(files).length === 0 ? (
          <p className="text-sm text-muted-foreground">No env files. Add one above.</p>
        ) : (
          Object.entries(files).map(([name, content]) => (
            <div key={name} className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-sm font-mono font-medium">{name}</span>
                <Button size="icon" variant="ghost" onClick={() => removeFile(name)} className="h-7 w-7">
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
              <Textarea
                value={content}
                onChange={(e) => setFiles({ ...files, [name]: e.target.value })}
                className="font-mono text-xs min-h-[100px]"
                placeholder="KEY=value"
              />
            </div>
          ))
        )}
        <div className="flex justify-end pt-2">
          <Button onClick={handleSave} disabled={saving} size="sm" className="gap-1.5">
            <Save className="h-3.5 w-3.5" />
            {saving ? "Saving..." : "Save to Disk"}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// --- Git Tab ---
function GitTab({
  env,
  initialDiverged = false,
  onDivergedHandled,
}: {
  env: EnvironmentWithAgent
  initialDiverged?: boolean
  onDivergedHandled?: () => void
}) {
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [pulling, setPulling] = useState(false)
  const [diverged, setDiverged] = useState(initialDiverged)
  const [gitError, setGitError] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)

  // Sync if parent sets initialDiverged after mount
  useEffect(() => {
    if (initialDiverged) {
      setDiverged(true)
    }
  }, [initialDiverged])

  const refreshStatus = useCallback(async () => {
    try {
      const data = await api.getEnvGitStatus(env.id)
      setGitStatus(data)
    } catch {
      // ignore
    }
  }, [env.id])

  useEffect(() => {
    refreshStatus().finally(() => setLoading(false))
  }, [refreshStatus])

  const handlePull = async (strategy: "ff-only" | "rebase" | "merge" = "ff-only") => {
    setPulling(true)
    setGitError(null)
    setDiverged(false)
    try {
      await api.pullEnvironment(env.id, strategy)
      onDivergedHandled?.()
      await refreshStatus()
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Pull failed"
      // 409 = diverged branches
      if (msg.includes("diverged") || msg.includes("rebase or merge")) {
        setDiverged(true)
      } else {
        setGitError(msg)
      }
    } finally {
      setPulling(false)
    }
  }

  const handleReset = async () => {
    if (!confirm("Reset to remote? This discards ALL local changes and commits.")) return
    setResetting(true)
    setGitError(null)
    setDiverged(false)
    try {
      await api.gitReset(env.id)
      onDivergedHandled?.()
      await refreshStatus()
    } catch (err) {
      setGitError(err instanceof Error ? err.message : "Reset failed")
    } finally {
      setResetting(false)
    }
  }

  if (loading) {
    return <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent mx-auto mt-8" />
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Git Status</CardTitle>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="secondary" onClick={() => handlePull()} disabled={pulling || resetting} className="gap-1.5">
              <ArrowDownToLine className="h-3.5 w-3.5" />
              {pulling ? "Pulling..." : "Pull"}
            </Button>
            <Button size="sm" variant="ghost" onClick={handleReset} disabled={pulling || resetting} className="gap-1.5 text-destructive hover:text-destructive">
              <RotateCcw className="h-3.5 w-3.5" />
              {resetting ? "Resetting..." : "Reset"}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {gitError && (
          <div className="mb-3 px-3 py-2 bg-destructive/10 border border-destructive/40 rounded-md text-destructive text-xs">
            {gitError}
            <button onClick={() => setGitError(null)} className="ml-2 underline">dismiss</button>
          </div>
        )}
        {diverged && (
          <div className="mb-3 px-3 py-2.5 bg-warning/10 border border-warning/40 rounded-md space-y-2">
            <p className="text-sm font-medium">Branches have diverged</p>
            <p className="text-xs text-muted-foreground">
              Local and remote branches have different commits. Choose how to reconcile:
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => handlePull("rebase")} disabled={pulling} className="text-xs">
                Rebase
              </Button>
              <Button size="sm" variant="secondary" onClick={() => handlePull("merge")} disabled={pulling} className="text-xs">
                Merge
              </Button>
              <Button size="sm" variant="ghost" onClick={handleReset} disabled={pulling || resetting} className="text-xs text-destructive hover:text-destructive">
                Reset to remote
              </Button>
            </div>
          </div>
        )}
        {gitStatus ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Branch:</span>{" "}
                <span className="font-mono font-medium">{gitStatus.branch}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Status:</span>{" "}
                <Badge variant={gitStatus.clean ? "success" : "warning"} className="text-[10px]">
                  {gitStatus.clean ? "Clean" : "Dirty"}
                </Badge>
              </div>
            </div>
            <div className="text-sm">
              <span className="text-muted-foreground">Last commit:</span>{" "}
              <span className="font-mono text-xs">{gitStatus.last_commit_hash.slice(0, 8)}</span>{" "}
              <span>{gitStatus.last_commit_message}</span>
            </div>
            {gitStatus.remote_branches.length > 0 && (
              <div className="text-sm">
                <span className="text-muted-foreground">Remote branches:</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {gitStatus.remote_branches.map((b) => (
                    <Badge key={b} variant="outline" className="text-[10px] font-mono">{b}</Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Unable to fetch git status.</p>
        )}
      </CardContent>
    </Card>
  )
}

// --- Logs Tab ---
function LogsTab({ envId }: { envId: string }) {
  const [logs, setLogs] = useState<string[]>([])
  const [running, setRunning] = useState(false)
  const [logKind, setLogKind] = useState<"dev_server" | "agent" | "editor">("dev_server")
  const logEndRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  const fetchLogs = useCallback(async () => {
    try {
      const data = await api.getDevServerLogs(envId, logKind)
      setLogs(data.lines)
      setRunning(data.running)
    } catch {
      // ignore
    }
  }, [envId, logKind])

  useEffect(() => {
    fetchLogs()
    const interval = setInterval(fetchLogs, 3000)
    return () => clearInterval(interval)
  }, [fetchLogs])

  useEffect(() => {
    if (autoScroll) {
      logEndRef.current?.scrollIntoView({ behavior: "smooth" })
    }
  }, [logs, autoScroll])

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Logs</CardTitle>
          <div className="flex items-center gap-2">
            <Select value={logKind} onValueChange={(v) => setLogKind(v as "dev_server" | "agent" | "editor")}>
              <SelectTrigger className="w-32 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="dev_server">Dev Server</SelectItem>
                <SelectItem value="agent">Agent</SelectItem>
                <SelectItem value="editor">Editor</SelectItem>
              </SelectContent>
            </Select>
            <Badge variant={running ? "success" : "secondary"} className="text-[10px]">
              {running ? "Running" : "Stopped"}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div
          className="bg-muted/50 rounded-md p-3 max-h-96 overflow-y-auto font-mono text-xs leading-relaxed"
          onScroll={(e) => {
            const el = e.currentTarget
            const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50
            setAutoScroll(atBottom)
          }}
        >
          {logs.length === 0 ? (
            <span className="text-muted-foreground">No logs available.</span>
          ) : (
            logs.map((line, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                <Ansi>{line}</Ansi>
              </div>
            ))
          )}
          <div ref={logEndRef} />
        </div>
      </CardContent>
    </Card>
  )
}

// --- Editor Tab ---
function EditorTab({ envId }: { envId: string }) {
  const [editorStatus, setEditorStatus] = useState<EditorStatus | null>(null)
  const [available, setAvailable] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const [status, avail] = await Promise.all([
        api.getEditorStatus(envId),
        api.isEditorAvailable(),
      ])
      setEditorStatus(status)
      setAvailable(avail)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [envId])

  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  const handleStart = async () => {
    setActionLoading(true)
    setStartError(null)
    try {
      const result = await api.startEditor(envId)
      setEditorStatus({ running: true, port: result.port, url: result.url })
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "Failed to start editor")
    } finally {
      setActionLoading(false)
    }
  }

  const handleStop = async () => {
    setActionLoading(true)
    try {
      await api.stopEditor(envId)
      setEditorStatus({ running: false, port: null, url: null })
    } catch {
      // error handled elsewhere
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) {
    return <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent mx-auto mt-8" />
  }

  if (available === false) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 gap-4">
          <Code2 className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm font-medium">code-server is not installed</p>
          <p className="text-sm text-muted-foreground text-center max-w-md">
            The editor requires{" "}
            <a href="https://github.com/coder/code-server" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              code-server
            </a>{" "}
            to be installed on the host machine.
          </p>
          <div className="bg-muted rounded-md px-4 py-2.5 font-mono text-xs select-all">
            curl -fsSL https://code-server.dev/install.sh | sh
          </div>
          <p className="text-xs text-muted-foreground">
            Restart the hub after installing.
          </p>
        </CardContent>
      </Card>
    )
  }

  if (!editorStatus?.running) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center py-16 gap-4">
          <Code2 className="h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Start the editor to open VS Code in your browser.
          </p>
          {startError && (
            <div className="px-4 py-2 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-xs max-w-md text-center">
              {startError}
            </div>
          )}
          <Button onClick={handleStart} disabled={actionLoading} className="gap-1.5">
            <Play className="h-3.5 w-3.5" />
            {actionLoading ? "Starting..." : "Start Editor"}
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge variant="success" className="text-[10px]">Running</Badge>
          <span className="text-xs text-muted-foreground font-mono">port {editorStatus.port}</span>
        </div>
        <div className="flex items-center gap-2">
          {editorStatus.url && (
            <a href={editorStatus.url} target="_blank" rel="noopener noreferrer">
              <Button size="sm" variant="ghost" className="gap-1.5 text-xs">
                <ExternalLink className="h-3 w-3" />
                Open in new tab
              </Button>
            </a>
          )}
          <Button size="sm" variant="secondary" onClick={handleStop} disabled={actionLoading} className="gap-1.5">
            <Square className="h-3.5 w-3.5" />
            {actionLoading ? "Stopping..." : "Stop Editor"}
          </Button>
        </div>
      </div>
      <div className="rounded-lg border border-border overflow-hidden" style={{ height: "calc(100vh - 320px)" }}>
        <iframe
          src={editorStatus.url || ""}
          className="w-full h-full border-0"
          title="Code Editor"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
        />
      </div>
    </div>
  )
}

// --- Agent Tab ---
function AgentTab({ env }: { env: EnvironmentWithAgent }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Agent</CardTitle>
      </CardHeader>
      <CardContent>
        {env.agent_connected ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="status-dot status-connected" />
              <span className="text-sm font-medium">Agent connected</span>
              {env.agent_name && (
                <Badge variant="outline" className="text-[10px]">{env.agent_name}</Badge>
              )}
            </div>
            {env.agent_id && (
              <Link
                to={`/agents/${env.agent_id}`}
                className="text-sm text-primary hover:underline"
              >
                View agent details
              </Link>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="status-dot status-disconnected" />
              <span className="text-sm text-muted-foreground">No agent connected</span>
            </div>
            <p className="text-xs text-muted-foreground">
              Start an agent from the action buttons above to enable AI-driven development workflows.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
