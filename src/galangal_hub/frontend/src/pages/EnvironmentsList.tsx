import { useEffect, useState, useCallback } from "react"
import { Link } from "react-router-dom"
import { useWebSocket } from "@/hooks/useWebSocket"
import { api } from "@/lib/api"
import type {
  EnvironmentWithAgent,
  EnvironmentCreate,
  Profile,
  StartMode,
  WSMessage,
  VaultProvider,
} from "@/types/api"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Plus, GitBranch, Server, Bot } from "lucide-react"
import { DopplerConnect, type DopplerSelection } from "@/components/vault/DopplerConnect"

const statusVariant: Record<string, "default" | "secondary" | "destructive" | "success" | "warning"> = {
  stopped: "secondary",
  cloning: "warning",
  ready: "warning",
  starting: "warning",
  running: "success",
  error: "destructive",
}

export function EnvironmentsList() {
  const [environments, setEnvironments] = useState<EnvironmentWithAgent[]>([])
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  const { lastMessage, isConnected: wsConnected } = useWebSocket("/ws/dashboard")

  const fetchData = useCallback(async () => {
    try {
      const [envs, profs] = await Promise.all([
        api.getEnvironments(),
        api.getProfiles(),
      ])
      setEnvironments(envs)
      setProfiles(profs)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch environments")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Refresh on WebSocket env_status messages
  useEffect(() => {
    if (lastMessage) {
      try {
        const msg: WSMessage = JSON.parse(lastMessage)
        if (msg.type === "env_status" || msg.type === "refresh") {
          fetchData()
        }
      } catch {
        // ignore
      }
    }
  }, [lastMessage, fetchData])

  const handleCreate = async (data: EnvironmentCreate) => {
    try {
      await api.createEnvironment(data)
      setCreateOpen(false)
      fetchData()
    } catch (err) {
      throw err
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-6 w-6 border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Environments</h1>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className={`status-dot ${wsConnected ? "status-connected" : "status-disconnected"}`} />
            <span>{wsConnected ? "Live" : "Disconnected"}</span>
          </div>
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button size="sm" className="gap-1.5">
                <Plus className="h-4 w-4" />
                New Environment
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle>Create Environment</DialogTitle>
              </DialogHeader>
              <CreateEnvironmentForm
                profiles={profiles}
                onSubmit={handleCreate}
                onCancel={() => setCreateOpen(false)}
              />
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {error && (
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {error}
        </div>
      )}

      {environments.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <Server className="h-10 w-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No environments yet. Create one to get started.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {environments.map((env) => (
            <EnvironmentCard key={env.id} env={env} />
          ))}
        </div>
      )}
    </div>
  )
}

function EnvironmentCard({ env }: { env: EnvironmentWithAgent }) {
  return (
    <Link to={`/environments/${env.id}`}>
      <Card className="card-hover">
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="font-semibold text-base break-words leading-tight">
                {env.name}
              </div>
              <div className="flex items-center gap-1.5 mt-1.5 text-xs text-muted-foreground">
                <GitBranch className="h-3 w-3 shrink-0" />
                <span className="truncate">{env.branch}</span>
              </div>
            </div>
            <Badge variant={statusVariant[env.status] || "secondary"} className="text-[10px] shrink-0">
              {env.status}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="text-xs text-muted-foreground truncate">
            {env.repo_url}
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px]">{env.provider}</Badge>
            <Badge variant="outline" className="text-[10px]">{env.start_mode}</Badge>
            {env.ports.length > 0 && (
              <span className="text-[10px] text-muted-foreground">
                ports: {env.ports.join(", ")}
              </span>
            )}
          </div>
          {env.agent_connected && (
            <div className="flex items-center gap-1.5 text-xs text-success">
              <Bot className="h-3 w-3" />
              <span>Agent: {env.agent_name || "connected"}</span>
            </div>
          )}
          {env.error_message && (
            <div className="text-xs text-destructive truncate">{env.error_message}</div>
          )}
        </CardContent>
      </Card>
    </Link>
  )
}

function CreateEnvironmentForm({
  profiles,
  onSubmit,
  onCancel,
}: {
  profiles: Profile[]
  onSubmit: (data: EnvironmentCreate) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState("")
  const [repoUrl, setRepoUrl] = useState("")
  const [branch, setBranch] = useState("main")
  const [profileId, setProfileId] = useState<string>("__none__")
  const [startMode, setStartMode] = useState<StartMode>("docker_compose")
  const [startCommand, setStartCommand] = useState("")
  const [stopCommand, setStopCommand] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Vault state
  const [vaultEnabled, setVaultEnabled] = useState(false)
  const [vaultProvider, setVaultProvider] = useState<VaultProvider | "">("")
  const [dopplerSelection, setDopplerSelection] = useState<DopplerSelection | null>(null)

  const buildVaultConfig = () => {
    if (!vaultEnabled || vaultProvider !== "doppler" || !dopplerSelection) return undefined
    return {
      enabled: true,
      provider: "doppler" as VaultProvider,
      doppler: dopplerSelection,
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await onSubmit({
        name,
        repo_url: repoUrl,
        branch,
        profile_id: profileId !== "__none__" ? profileId : undefined,
        start_mode: startMode,
        start_command: startMode === "shell" ? startCommand || undefined : undefined,
        stop_command: startMode === "shell" ? stopCommand || undefined : undefined,
        vault: buildVaultConfig(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create environment")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="px-3 py-2 bg-destructive/10 border border-destructive/40 rounded text-destructive text-sm">
          {error}
        </div>
      )}

      <div className="space-y-2">
        <label className="text-sm font-medium">Name</label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-project"
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">Repository URL</label>
        <Input
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          placeholder="https://github.com/user/repo.git"
          required
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-2">
          <label className="text-sm font-medium">Branch</label>
          <Input
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            placeholder="main"
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium">Profile</label>
          <Select value={profileId} onValueChange={setProfileId}>
            <SelectTrigger>
              <SelectValue placeholder="None" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">None</SelectItem>
              {profiles.map((p) => (
                <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
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
            id="vault-enabled"
            checked={vaultEnabled}
            onChange={(e) => setVaultEnabled(e.target.checked)}
            className="rounded border-border"
          />
          <label htmlFor="vault-enabled" className="text-sm font-medium">
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
              <DopplerConnect onChange={setDopplerSelection} />
            )}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">Start Mode</label>
        <Select value={startMode} onValueChange={(v) => setStartMode(v as StartMode)}>
          <SelectTrigger>
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

      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={submitting || !name || !repoUrl}>
          {submitting ? "Creating..." : "Create"}
        </Button>
      </div>
    </form>
  )
}
