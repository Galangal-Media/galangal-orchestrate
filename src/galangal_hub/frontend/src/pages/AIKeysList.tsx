import { useEffect, useState, useCallback } from "react"
import { api } from "@/lib/api"
import type { CredentialProfile, CredentialProfileCreate, AIProvider, ClaudeAccount, CLIAccountProvider } from "@/types/api"
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
import { Plus, Pencil, Trash2, FlaskConical, Key, Eye, EyeOff, LogIn, LogOut, RefreshCw, User, ExternalLink, Terminal } from "lucide-react"
import { WebTerminal } from "@/components/environment/WebTerminal"

const providerColors: Record<string, "default" | "secondary" | "destructive" | "success" | "warning"> = {
  claude: "default",
  openai: "success",
  gemini: "warning",
}

export function AIKeysList() {
  const [credentials, setCredentials] = useState<CredentialProfile[]>([])
  const [accounts, setAccounts] = useState<ClaudeAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [editProfile, setEditProfile] = useState<CredentialProfile | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { valid: boolean; error?: string } | null>>({})
  const [testingId, setTestingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // Claude accounts state
  const [accountCreateOpen, setAccountCreateOpen] = useState(false)
  const [accountName, setAccountName] = useState("")
  const [accountProvider, setAccountProvider] = useState<CLIAccountProvider>("claude")
  const [creatingAccount, setCreatingAccount] = useState(false)
  const [loggingInId, setLoggingInId] = useState<string | null>(null)
  const [deletingAccountId, setDeletingAccountId] = useState<string | null>(null)

  const fetchCredentials = useCallback(async () => {
    try {
      const [creds, accts] = await Promise.all([
        api.getCredentialProfiles(),
        api.getClaudeAccounts(),
      ])
      setCredentials(creds)
      setAccounts(accts)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch credentials")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchCredentials()
  }, [fetchCredentials])

  const handleCreateAccount = async () => {
    if (!accountName.trim()) return
    setCreatingAccount(true)
    try {
      await api.createClaudeAccount({ name: accountName.trim(), provider: accountProvider })
      setAccountName("")
      setAccountProvider("claude")
      setAccountCreateOpen(false)
      fetchCredentials()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create account")
    } finally {
      setCreatingAccount(false)
    }
  }

  const handleLogin = (accountId: string) => {
    setLoggingInId(accountId)
  }

  const handleTerminalClose = useCallback(() => {
    setLoggingInId(null)
    fetchCredentials()
  }, [fetchCredentials])

  const handleLogout = async (accountId: string) => {
    try {
      await api.logoutClaudeAccount(accountId)
      fetchCredentials()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to logout")
    }
  }

  const handleRefreshStatus = async (accountId: string) => {
    try {
      await api.getClaudeAccountStatus(accountId)
      fetchCredentials()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh status")
    }
  }

  const handleDeleteAccount = async (accountId: string) => {
    if (!confirm("Delete this Claude Max account? This cannot be undone.")) return
    setDeletingAccountId(accountId)
    try {
      await api.deleteClaudeAccount(accountId)
      fetchCredentials()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete")
    } finally {
      setDeletingAccountId(null)
    }
  }

  const handleTest = async (profileId: string) => {
    setTestingId(profileId)
    try {
      const result = await api.testCredentialProfile(profileId)
      setTestResults((prev) => ({ ...prev, [profileId]: result }))
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [profileId]: { valid: false, error: err instanceof Error ? err.message : "Test failed" },
      }))
    } finally {
      setTestingId(null)
    }
  }

  const handleDelete = async (profileId: string) => {
    if (!confirm("Delete this API key? This cannot be undone.")) return
    setDeletingId(profileId)
    try {
      await api.deleteCredentialProfile(profileId)
      fetchCredentials()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete")
    } finally {
      setDeletingId(null)
    }
  }

  const handleCreateOrUpdate = async (data: CredentialProfileCreate) => {
    if (editProfile) {
      await api.updateCredentialProfile(editProfile.id, data)
    } else {
      await api.createCredentialProfile(data)
    }
    setCreateOpen(false)
    setEditProfile(null)
    fetchCredentials()
  }

  const openEdit = (profile: CredentialProfile) => {
    setEditProfile(profile)
    setCreateOpen(true)
  }

  // Group by provider
  const grouped = credentials.reduce<Record<string, CredentialProfile[]>>((acc, c) => {
    const key = c.provider
    if (!acc[key]) acc[key] = []
    acc[key].push(c)
    return acc
  }, {})

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
        <h1 className="text-2xl font-bold tracking-tight">AI Keys</h1>
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
              Add Key
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>{editProfile ? "Edit API Key" : "Add API Key"}</DialogTitle>
            </DialogHeader>
            <CredentialForm
              initial={editProfile}
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

      {/* Claude Max Accounts Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
            Subscription Accounts
          </h2>
          <Dialog open={accountCreateOpen} onOpenChange={setAccountCreateOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline" className="gap-1.5 h-7 text-xs">
                <Plus className="h-3 w-3" />
                Add Account
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-sm">
              <DialogHeader>
                <DialogTitle>Add Subscription Account</DialogTitle>
              </DialogHeader>
              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Provider</label>
                  <Select value={accountProvider} onValueChange={(v) => setAccountProvider(v as CLIAccountProvider)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="claude">Claude Max</SelectItem>
                      <SelectItem value="codex">Codex (OpenAI)</SelectItem>
                      <SelectItem value="gemini">Gemini</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Account Name</label>
                  <Input
                    value={accountName}
                    onChange={(e) => setAccountName(e.target.value)}
                    placeholder={accountProvider === "claude" ? "e.g. Charles Max" : accountProvider === "codex" ? "e.g. Charles Codex" : "e.g. Charles Gemini"}
                    onKeyDown={(e) => e.key === "Enter" && handleCreateAccount()}
                  />
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => setAccountCreateOpen(false)}>
                    Cancel
                  </Button>
                  <Button
                    onClick={handleCreateAccount}
                    disabled={creatingAccount || !accountName.trim()}
                  >
                    {creatingAccount ? "Creating..." : "Create"}
                  </Button>
                </div>
              </div>
            </DialogContent>
          </Dialog>
        </div>

        {accounts.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground border border-dashed rounded-lg">
            <User className="h-8 w-8 mx-auto mb-2 opacity-40" />
            <p className="text-xs">No subscription accounts. Add one to use Claude Max, Codex, or Gemini CLI login.</p>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {accounts.map((account) => (
              <Card key={account.id} className={loggingInId === account.id ? "md:col-span-2 lg:col-span-3" : ""}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="font-semibold text-base break-words leading-tight">
                        {account.name}
                      </div>
                      {account.email && (
                        <div className="text-xs text-muted-foreground mt-0.5">{account.email}</div>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Badge variant={providerColors[account.provider] || "secondary"} className="text-[10px]">
                        {account.provider === "claude" ? "Claude" : account.provider === "codex" ? "Codex" : "Gemini"}
                      </Badge>
                      {account.subscription_type && (
                        <Badge variant="secondary" className="text-[10px]">
                          {account.subscription_type}
                        </Badge>
                      )}
                      <Badge
                        variant={account.logged_in ? "success" : "destructive"}
                        className="text-[10px]"
                      >
                        {account.logged_in ? "Logged in" : "Logged out"}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {loggingInId === account.id && (
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                          <Terminal className="h-3 w-3" />
                          <span className="font-medium">Terminal</span>
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setLoggingInId(null)}
                          className="h-6 text-[11px] text-muted-foreground"
                        >
                          Close
                        </Button>
                      </div>
                      <WebTerminal
                        wsUrl={`${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/claude-accounts/${account.id}/terminal`}
                        onClose={handleTerminalClose}
                      />
                      <TerminalInstructions provider={account.provider} />
                    </div>
                  )}

                  <div className="flex items-center gap-1.5">
                    {account.logged_in ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleLogout(account.id)}
                        className="gap-1 h-7 text-xs"
                      >
                        <LogOut className="h-3 w-3" />
                        Logout
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleLogin(account.id)}
                        disabled={loggingInId === account.id}
                        className="gap-1 h-7 text-xs"
                      >
                        <LogIn className="h-3 w-3" />
                        {loggingInId === account.id ? "Waiting..." : "Login"}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleRefreshStatus(account.id)}
                      className="gap-1 h-7 text-xs"
                    >
                      <RefreshCw className="h-3 w-3" />
                      Refresh
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => handleDeleteAccount(account.id)}
                      disabled={deletingAccountId === account.id}
                      className="gap-1 h-7 text-xs text-destructive hover:text-destructive"
                    >
                      <Trash2 className="h-3 w-3" />
                      {deletingAccountId === account.id ? "..." : "Delete"}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* API Keys Section */}
      {credentials.length === 0 && accounts.length > 0 ? (
        <div className="text-center py-8 text-muted-foreground border border-dashed rounded-lg">
          <Key className="h-8 w-8 mx-auto mb-2 opacity-40" />
          <p className="text-xs">No API keys yet. Add one for API-key-based authentication.</p>
        </div>
      ) : credentials.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <Key className="h-10 w-10 mx-auto mb-3 opacity-40" />
          <p className="text-sm">No API keys yet. Add one to get started.</p>
        </div>
      ) : (
        Object.entries(grouped).map(([provider, profiles]) => (
          <div key={provider} className="space-y-3">
            <h2 className="text-sm font-medium text-muted-foreground uppercase tracking-wider">
              {provider}
            </h2>
            <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {profiles.map((profile) => {
                const testResult = testResults[profile.id]
                return (
                  <Card key={profile.id}>
                    <CardHeader className="pb-2">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="font-semibold text-base break-words leading-tight">
                            {profile.name}
                          </div>
                        </div>
                        <Badge variant={providerColors[profile.provider] || "secondary"} className="text-[10px] shrink-0">
                          {profile.provider}
                        </Badge>
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="space-y-1">
                        {Object.entries(profile.credentials).map(([key, value]) => (
                          <div key={key} className="flex items-center gap-2 text-xs">
                            <span className="text-muted-foreground font-mono">{key}:</span>
                            <span className="font-mono truncate">{value}</span>
                          </div>
                        ))}
                      </div>

                      {testResult && (
                        <div
                          className={`px-2 py-1.5 rounded text-xs ${
                            testResult.valid
                              ? "bg-success/10 border border-success/40 text-success"
                              : "bg-destructive/10 border border-destructive/40 text-destructive"
                          }`}
                        >
                          {testResult.valid ? "Valid" : testResult.error || "Invalid"}
                        </div>
                      )}

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
                          onClick={() => handleTest(profile.id)}
                          disabled={testingId === profile.id}
                          className="gap-1 h-7 text-xs"
                        >
                          <FlaskConical className="h-3 w-3" />
                          {testingId === profile.id ? "Testing..." : "Test"}
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
                )
              })}
            </div>
          </div>
        ))
      )}
    </div>
  )
}

function TerminalInstructions({ provider }: { provider: string }) {
  if (provider === "codex") {
    return (
      <div className="px-3 py-2.5 bg-muted/50 border rounded-md text-xs text-muted-foreground space-y-1.5">
        <p className="font-medium text-foreground">Steps to sign in with Codex:</p>
        <ol className="list-decimal list-inside space-y-1 ml-1">
          <li>First ensure Codex is installed: <code className="bg-muted px-1 rounded text-foreground">npm install -g @openai/codex</code></li>
          <li>Run <code className="bg-muted px-1 rounded text-foreground">codex</code> to launch it</li>
          <li>Follow the login prompts to sign in with your OpenAI account</li>
          <li>Once signed in, type <code className="bg-muted px-1 rounded text-foreground">/quit</code> to exit Codex</li>
          <li>Type <code className="bg-muted px-1 rounded text-foreground">exit</code> to close the terminal</li>
        </ol>
        <p className="pt-0.5">Codex uses your ChatGPT Pro/Plus subscription. Visit <a href="https://chatgpt.com/codex/settings/usage" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">usage settings</a> to check your limits.</p>
      </div>
    )
  }

  if (provider === "gemini") {
    return (
      <div className="px-3 py-2.5 bg-muted/50 border rounded-md text-xs text-muted-foreground space-y-1.5">
        <p className="font-medium text-foreground">Steps to sign in with Gemini CLI:</p>
        <ol className="list-decimal list-inside space-y-1 ml-1">
          <li>First ensure Gemini CLI is installed: <code className="bg-muted px-1 rounded text-foreground">npm install -g @google/gemini-cli</code></li>
          <li>Run <code className="bg-muted px-1 rounded text-foreground">gemini</code> to launch it</li>
          <li>Follow the login prompts to sign in with your Google account</li>
          <li>Once signed in, exit the CLI</li>
          <li>Type <code className="bg-muted px-1 rounded text-foreground">exit</code> to close the terminal</li>
        </ol>
      </div>
    )
  }

  // Default: Claude
  return (
    <div className="px-3 py-2.5 bg-muted/50 border rounded-md text-xs text-muted-foreground space-y-1.5">
      <p className="font-medium text-foreground">Steps to sign in with Claude Max:</p>
      <ol className="list-decimal list-inside space-y-1 ml-1">
        <li>Type <code className="bg-muted px-1 rounded text-foreground">claude auth login</code> and press Enter</li>
        <li>Copy the URL that appears and open it in your browser</li>
        <li>Sign in with your Anthropic account and authorize access</li>
        <li>The CLI will detect the login automatically once complete</li>
        <li>Type <code className="bg-muted px-1 rounded text-foreground">exit</code> to close the terminal</li>
      </ol>
      <p className="pt-0.5">Use <code className="bg-muted px-1 rounded text-foreground">claude auth status</code> to verify your login, or <code className="bg-muted px-1 rounded text-foreground">claude auth logout</code> to sign out.</p>
    </div>
  )
}

function CredentialForm({
  initial,
  onSubmit,
  onCancel,
}: {
  initial: CredentialProfile | null
  onSubmit: (data: CredentialProfileCreate) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name || "")
  const [provider, setProvider] = useState<AIProvider>(initial?.provider || "claude")
  const [apiKey, setApiKey] = useState("")
  const [orgId, setOrgId] = useState("")
  const [projectId, setProjectId] = useState("")
  const [showKey, setShowKey] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const credentials: Record<string, string> = {}
      if (apiKey) credentials.api_key = apiKey
      if (provider === "claude" && orgId) credentials.org_id = orgId
      if (provider === "openai" && orgId) credentials.org_id = orgId
      if (provider === "gemini" && projectId) credentials.project_id = projectId

      // For updates without new key, only send non-credential fields
      if (initial && !apiKey) {
        await onSubmit({ name, provider, credentials: initial.credentials })
      } else {
        if (!apiKey) {
          setError("API key is required")
          setSubmitting(false)
          return
        }
        await onSubmit({ name, provider, credentials })
      }
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
        <label className="text-sm font-medium">Name</label>
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Production Claude Key"
          required
        />
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium">Provider</label>
        <Select value={provider} onValueChange={(v) => setProvider(v as AIProvider)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="claude">Claude</SelectItem>
            <SelectItem value="openai">OpenAI (Codex)</SelectItem>
            <SelectItem value="gemini">Gemini</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Provider-specific instructions */}
      {provider === "claude" && (
        <div className="px-3 py-2.5 bg-muted/50 border rounded-md text-xs text-muted-foreground space-y-1">
          <p>To get a Claude API key:</p>
          <ol className="list-decimal list-inside space-y-0.5 ml-1">
            <li>Go to the <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">Anthropic Console <ExternalLink className="h-2.5 w-2.5" /></a></li>
            <li>Click <span className="font-medium text-foreground">Create Key</span></li>
            <li>Copy the key (starts with <code className="text-[11px] bg-muted px-1 rounded">sk-ant-</code>)</li>
          </ol>
        </div>
      )}
      {provider === "openai" && (
        <div className="px-3 py-2.5 bg-muted/50 border rounded-md text-xs text-muted-foreground space-y-1">
          <p>To get an OpenAI API key for Codex:</p>
          <ol className="list-decimal list-inside space-y-0.5 ml-1">
            <li>Go to <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">OpenAI Platform <ExternalLink className="h-2.5 w-2.5" /></a></li>
            <li>Click <span className="font-medium text-foreground">Create new secret key</span></li>
            <li>Copy the key (starts with <code className="text-[11px] bg-muted px-1 rounded">sk-</code>)</li>
          </ol>
          <p className="pt-0.5">Codex requires a funded OpenAI account with API access enabled.</p>
        </div>
      )}
      {provider === "gemini" && (
        <div className="px-3 py-2.5 bg-muted/50 border rounded-md text-xs text-muted-foreground space-y-1">
          <p>To get a Gemini API key:</p>
          <ol className="list-decimal list-inside space-y-0.5 ml-1">
            <li>Go to <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-0.5">Google AI Studio <ExternalLink className="h-2.5 w-2.5" /></a></li>
            <li>Click <span className="font-medium text-foreground">Create API key</span></li>
            <li>Select or create a Google Cloud project</li>
            <li>Copy the generated key</li>
          </ol>
        </div>
      )}

      <div className="space-y-2">
        <label className="text-sm font-medium">
          API Key {initial && <span className="text-muted-foreground font-normal">(leave blank to keep current)</span>}
        </label>
        <div className="relative">
          <Input
            type={showKey ? "text" : "password"}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={
              initial
                ? "Enter new key to update"
                : provider === "claude"
                  ? "sk-ant-..."
                  : provider === "openai"
                    ? "sk-..."
                    : "AIza..."
            }
            className="pr-10"
          />
          <button
            type="button"
            onClick={() => setShowKey(!showKey)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {(provider === "claude" || provider === "openai") && (
        <div className="space-y-2">
          <label className="text-sm font-medium">
            Organization ID <span className="text-muted-foreground font-normal">(optional)</span>
          </label>
          <Input
            value={orgId}
            onChange={(e) => setOrgId(e.target.value)}
            placeholder={provider === "claude" ? "org-..." : "org-..."}
          />
        </div>
      )}

      {provider === "gemini" && (
        <div className="space-y-2">
          <label className="text-sm font-medium">
            Project ID <span className="text-muted-foreground font-normal">(optional)</span>
          </label>
          <Input
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            placeholder="my-gcp-project"
          />
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={submitting || !name}>
          {submitting ? "Saving..." : initial ? "Update" : "Add Key"}
        </Button>
      </div>
    </form>
  )
}
