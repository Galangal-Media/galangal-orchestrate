import { useEffect, useState, useCallback } from "react"
import { api } from "@/lib/api"
import type { Profile, ProfileCreate, CredentialProfile, ClaudeAccount } from "@/types/api"
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
import { Plus, Pencil, Trash2, Layers } from "lucide-react"

export function ProfilesList() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [credentials, setCredentials] = useState<CredentialProfile[]>([])
  const [claudeAccounts, setClaudeAccounts] = useState<ClaudeAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [editProfile, setEditProfile] = useState<Profile | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const [p, c, a] = await Promise.all([
        api.getProfiles(),
        api.getCredentialProfiles(),
        api.getClaudeAccounts(),
      ])
      setProfiles(p)
      setCredentials(c)
      setClaudeAccounts(a)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch profiles")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const handleDelete = async (profileId: string) => {
    if (!confirm("Delete this profile?")) return
    setDeletingId(profileId)
    try {
      await api.deleteProfile(profileId)
      fetchData()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete")
    } finally {
      setDeletingId(null)
    }
  }

  const handleCreateOrUpdate = async (data: ProfileCreate) => {
    if (editProfile) {
      await api.updateProfile(editProfile.id, data)
    } else {
      await api.createProfile(data)
    }
    setCreateOpen(false)
    setEditProfile(null)
    fetchData()
  }

  const openEdit = (profile: Profile) => {
    setEditProfile(profile)
    setCreateOpen(true)
  }

  const getCredName = (id: string | null) => {
    if (!id) return null
    return credentials.find((c) => c.id === id)?.name || "Unknown"
  }

  const getAccountName = (id: string | null) => {
    if (!id) return null
    return claudeAccounts.find((a) => a.id === id)?.name || "Unknown"
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
        <h1 className="text-2xl font-bold tracking-tight">Profiles</h1>
        <Dialog
          open={createOpen}
          onOpenChange={(open) => {
            setCreateOpen(open)
            if (!open) setEditProfile(null)
          }}
        >
          <DialogTrigger asChild>
            <Button size="sm" className="gap-1.5">
              <Plus className="h-4 w-4" />
              New Profile
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>{editProfile ? "Edit Profile" : "Create Profile"}</DialogTitle>
            </DialogHeader>
            <ProfileForm
              initial={editProfile}
              credentials={credentials}
              claudeAccounts={claudeAccounts}
              onSubmit={handleCreateOrUpdate}
              onCancel={() => {
                setCreateOpen(false)
                setEditProfile(null)
              }}
            />
          </DialogContent>
        </Dialog>
      </div>

      {error && (
        <div className="px-4 py-3 bg-destructive/10 border border-destructive/40 rounded-lg text-destructive text-sm">
          {error}
          <button onClick={() => setError(null)} className="ml-2 underline text-xs">dismiss</button>
        </div>
      )}

      <p className="text-sm text-muted-foreground">
        Profiles bundle multiple AI credentials together. Assign a profile to an environment to inject all its API keys when starting an agent.
      </p>

      {profiles.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <Layers className="h-10 w-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No profiles yet. Create one to bundle your AI keys.</p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {profiles.map((profile) => (
            <Card key={profile.id}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="font-semibold text-base break-words leading-tight">
                    {profile.name}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-1.5">
                  {profile.claude_account_id && (
                    <div className="flex items-center gap-2">
                      <Badge variant="default" className="text-[10px]">Claude Max</Badge>
                      <span className="text-xs text-muted-foreground">{getAccountName(profile.claude_account_id)}</span>
                    </div>
                  )}
                  {profile.claude_credential_id && !profile.claude_account_id && (
                    <div className="flex items-center gap-2">
                      <Badge variant="default" className="text-[10px]">Claude</Badge>
                      <span className="text-xs text-muted-foreground">{getCredName(profile.claude_credential_id)}</span>
                    </div>
                  )}
                  {profile.codex_account_id && (
                    <div className="flex items-center gap-2">
                      <Badge variant="success" className="text-[10px]">Codex Pro</Badge>
                      <span className="text-xs text-muted-foreground">{getAccountName(profile.codex_account_id)}</span>
                    </div>
                  )}
                  {profile.codex_credential_id && !profile.codex_account_id && (
                    <div className="flex items-center gap-2">
                      <Badge variant="success" className="text-[10px]">Codex</Badge>
                      <span className="text-xs text-muted-foreground">{getCredName(profile.codex_credential_id)}</span>
                    </div>
                  )}
                  {profile.gemini_account_id && (
                    <div className="flex items-center gap-2">
                      <Badge variant="warning" className="text-[10px]">Gemini Sub</Badge>
                      <span className="text-xs text-muted-foreground">{getAccountName(profile.gemini_account_id)}</span>
                    </div>
                  )}
                  {profile.gemini_credential_id && !profile.gemini_account_id && (
                    <div className="flex items-center gap-2">
                      <Badge variant="warning" className="text-[10px]">Gemini</Badge>
                      <span className="text-xs text-muted-foreground">{getCredName(profile.gemini_credential_id)}</span>
                    </div>
                  )}
                  {!profile.claude_credential_id && !profile.claude_account_id && !profile.codex_credential_id && !profile.codex_account_id && !profile.gemini_credential_id && !profile.gemini_account_id && (
                    <span className="text-xs text-muted-foreground">No credentials linked</span>
                  )}
                </div>

                <div className="flex items-center gap-1.5 pt-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => openEdit(profile)}
                    className="gap-1 h-7 text-xs"
                  >
                    <Pencil className="h-3 w-3" />
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => handleDelete(profile.id)}
                    disabled={deletingId === profile.id}
                    className="gap-1 h-7 text-xs text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3" />
                    {deletingId === profile.id ? "..." : "Delete"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function ProviderAuthSection({
  label,
  mode,
  onModeChange,
  apiKeyCreds,
  apiKeyValue,
  onApiKeyChange,
  subscriptionAccounts,
  subscriptionValue,
  onSubscriptionChange,
  subscriptionLabel,
}: {
  label: string
  mode: "none" | "api_key" | "subscription"
  onModeChange: (v: "none" | "api_key" | "subscription") => void
  apiKeyCreds: CredentialProfile[]
  apiKeyValue: string
  onApiKeyChange: (v: string) => void
  subscriptionAccounts: ClaudeAccount[]
  subscriptionValue: string
  onSubscriptionChange: (v: string) => void
  subscriptionLabel: string
}) {
  const loggedIn = subscriptionAccounts.filter((a) => a.logged_in)
  const loggedOut = subscriptionAccounts.filter((a) => !a.logged_in)

  return (
    <>
      <div className="space-y-2">
        <label className="text-sm font-medium">{label}</label>
        <Select value={mode} onValueChange={(v) => onModeChange(v as "none" | "api_key" | "subscription")}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">None</SelectItem>
            <SelectItem value="api_key">API Key</SelectItem>
            <SelectItem value="subscription">{subscriptionLabel} Subscription</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {mode === "api_key" && (
        <div className="space-y-2">
          <label className="text-sm font-medium text-muted-foreground">{label} API Key</label>
          <Select value={apiKeyValue} onValueChange={onApiKeyChange}>
            <SelectTrigger>
              <SelectValue placeholder="None" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">None</SelectItem>
              {apiKeyCreds.map((c) => (
                <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {mode === "subscription" && (
        <div className="space-y-2">
          <label className="text-sm font-medium text-muted-foreground">{label} Account</label>
          <Select value={subscriptionValue} onValueChange={onSubscriptionChange}>
            <SelectTrigger>
              <SelectValue placeholder="None" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">None</SelectItem>
              {loggedIn.map((a) => (
                <SelectItem key={a.id} value={a.id}>
                  {a.name}{a.email ? ` (${a.email})` : ""}
                </SelectItem>
              ))}
              {loggedOut.map((a) => (
                <SelectItem key={a.id} value={a.id} disabled>
                  {a.name} (not logged in)
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {loggedIn.length === 0 && subscriptionAccounts.length > 0 && (
            <p className="text-xs text-muted-foreground">No logged-in accounts. Go to AI Keys to log in first.</p>
          )}
          {subscriptionAccounts.length === 0 && (
            <p className="text-xs text-muted-foreground">No {label.toLowerCase()} subscription accounts. Add one in AI Keys first.</p>
          )}
        </div>
      )}
    </>
  )
}

function ProfileForm({
  initial,
  credentials,
  claudeAccounts,
  onSubmit,
  onCancel,
}: {
  initial: Profile | null
  credentials: CredentialProfile[]
  claudeAccounts: ClaudeAccount[]
  onSubmit: (data: ProfileCreate) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name || "")
  const [claudeMode, setClaudeMode] = useState<"none" | "api_key" | "subscription">(
    initial?.claude_account_id ? "subscription" : initial?.claude_credential_id ? "api_key" : "none"
  )
  const [claudeId, setClaudeId] = useState(initial?.claude_credential_id || "__none__")
  const [claudeAccountId, setClaudeAccountId] = useState(initial?.claude_account_id || "__none__")
  const [codexMode, setCodexMode] = useState<"none" | "api_key" | "subscription">(
    initial?.codex_account_id ? "subscription" : initial?.codex_credential_id ? "api_key" : "none"
  )
  const [codexId, setCodexId] = useState(initial?.codex_credential_id || "__none__")
  const [codexAccountId, setCodexAccountId] = useState(initial?.codex_account_id || "__none__")
  const [geminiMode, setGeminiMode] = useState<"none" | "api_key" | "subscription">(
    initial?.gemini_account_id ? "subscription" : initial?.gemini_credential_id ? "api_key" : "none"
  )
  const [geminiId, setGeminiId] = useState(initial?.gemini_credential_id || "__none__")
  const [geminiAccountId, setGeminiAccountId] = useState(initial?.gemini_account_id || "__none__")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const claudeCreds = credentials.filter((c) => c.provider === "claude")
  const codexCreds = credentials.filter((c) => c.provider === "openai")
  const geminiCreds = credentials.filter((c) => c.provider === "gemini")
  const claudeSubscriptions = claudeAccounts.filter((a) => a.provider === "claude")
  const codexSubscriptions = claudeAccounts.filter((a) => a.provider === "codex")
  const geminiSubscriptions = claudeAccounts.filter((a) => a.provider === "gemini")

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await onSubmit({
        name,
        claude_credential_id: claudeMode === "api_key" && claudeId !== "__none__" ? claudeId : null,
        claude_account_id: claudeMode === "subscription" && claudeAccountId !== "__none__" ? claudeAccountId : null,
        codex_credential_id: codexMode === "api_key" && codexId !== "__none__" ? codexId : null,
        codex_account_id: codexMode === "subscription" && codexAccountId !== "__none__" ? codexAccountId : null,
        gemini_credential_id: geminiMode === "api_key" && geminiId !== "__none__" ? geminiId : null,
        gemini_account_id: geminiMode === "subscription" && geminiAccountId !== "__none__" ? geminiAccountId : null,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save")
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
        <label className="text-sm font-medium">Profile Name</label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Galangal Production"
          required
        />
      </div>

      <ProviderAuthSection
        label="Claude"
        mode={claudeMode}
        onModeChange={(v) => setClaudeMode(v)}
        apiKeyCreds={claudeCreds}
        apiKeyValue={claudeId}
        onApiKeyChange={setClaudeId}
        subscriptionAccounts={claudeSubscriptions}
        subscriptionValue={claudeAccountId}
        onSubscriptionChange={setClaudeAccountId}
        subscriptionLabel="Max"
      />

      <ProviderAuthSection
        label="Codex (OpenAI)"
        mode={codexMode}
        onModeChange={(v) => setCodexMode(v)}
        apiKeyCreds={codexCreds}
        apiKeyValue={codexId}
        onApiKeyChange={setCodexId}
        subscriptionAccounts={codexSubscriptions}
        subscriptionValue={codexAccountId}
        onSubscriptionChange={setCodexAccountId}
        subscriptionLabel="Pro"
      />

      <ProviderAuthSection
        label="Gemini"
        mode={geminiMode}
        onModeChange={(v) => setGeminiMode(v)}
        apiKeyCreds={geminiCreds}
        apiKeyValue={geminiId}
        onApiKeyChange={setGeminiId}
        subscriptionAccounts={geminiSubscriptions}
        subscriptionValue={geminiAccountId}
        onSubscriptionChange={setGeminiAccountId}
        subscriptionLabel="Subscription"
      />

      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={submitting || !name}>
          {submitting ? "Saving..." : initial ? "Update" : "Create"}
        </Button>
      </div>
    </form>
  )
}
