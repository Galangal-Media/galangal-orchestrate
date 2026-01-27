# Hub Configuration

## Agent Configuration

Enable hub connectivity in your project's `.galangal/config.yaml`:

```yaml
hub:
  # Enable hub connection
  enabled: true

  # Hub server WebSocket URL
  url: ws://your-server:8080/ws/agent

  # API key (if hub requires authentication)
  api_key: your-secret-key

  # Heartbeat interval in seconds (default: 30)
  heartbeat_interval: 30

  # Reconnect interval after disconnect (default: 5)
  reconnect_interval: 5

  # Custom agent name (default: hostname)
  agent_name: my-workstation
```

### URL Formats

| Deployment | URL Format |
|------------|------------|
| Plain HTTP | `ws://server:8080/ws/agent` |
| HTTPS/Traefik | `wss://hub.yourdomain.com/ws/agent` |
| Tailscale | `wss://galangal-hub/ws/agent` |

### Minimal Configuration

```yaml
hub:
  enabled: true
  url: ws://192.168.1.100:8080/ws/agent
```

### Full Configuration

```yaml
hub:
  enabled: true
  url: wss://hub.example.com/ws/agent
  api_key: abc123def456
  heartbeat_interval: 30
  reconnect_interval: 5
  agent_name: charles-laptop
```

## Hub Server Configuration

The hub server is configured via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_HOST` | `0.0.0.0` | Host to bind to |
| `HUB_PORT` | `8080` | Port to listen on |
| `HUB_DB_PATH` | `/data/hub.db` | SQLite database path |
| `HUB_API_KEY` | (none) | API key for agent authentication |
| `HUB_USERNAME` | (none) | Dashboard login username |
| `HUB_PASSWORD` | (none) | Dashboard login password |

### Dashboard Authentication

To require login for the web dashboard, set both `HUB_USERNAME` and `HUB_PASSWORD`:

```yaml
services:
  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    environment:
      - HUB_USERNAME=admin
      - HUB_PASSWORD=your-secure-password
      - HUB_API_KEY=agent-key-for-connections
    volumes:
      - galangal-hub-data:/data
```

When enabled:
- Dashboard routes redirect to `/login` if not authenticated
- Session lasts 7 days (cookie-based)
- Logout available via `/logout`

**Note:** `HUB_API_KEY` is for agent WebSocket connections. `HUB_USERNAME`/`HUB_PASSWORD` is for browser dashboard access. They serve different purposes and can be used independently.

### Docker Compose Example

```yaml
services:
  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    environment:
      - HUB_HOST=0.0.0.0
      - HUB_PORT=8080
      - HUB_USERNAME=admin
      - HUB_PASSWORD=${HUB_PASSWORD}
      - HUB_API_KEY=${HUB_API_KEY:-}
    volumes:
      - galangal-hub-data:/data
```

### Using .env File

Create a `.env` file:

```bash
HUB_PORT=8080
HUB_USERNAME=admin
HUB_PASSWORD=your-secure-password
HUB_API_KEY=your-agent-api-key
```

## CLI Commands

### galangal hub status

Show current hub configuration:

```bash
galangal hub status
```

Output:
```
Hub Configuration

Enabled       Yes
URL           ws://localhost:8080/ws/agent
API Key       ****
Heartbeat     30s
Agent Name    <hostname>

Hub is enabled.
Use galangal hub test to verify the connection.
```

### galangal hub test

Test connection to the hub server with detailed diagnostics:

```bash
galangal hub test
```

This command performs step-by-step testing to identify connection problems:

1. **websockets module** - Checks the required library is installed
2. **DNS resolution** - Verifies the hostname can be resolved
3. **TCP connection** - Tests that the server is reachable
4. **TLS handshake** - For `wss://` URLs, validates SSL/TLS
5. **WebSocket connection** - Tests the WebSocket upgrade
6. **Authentication** - Verifies API key is accepted
7. **Agent registration** - Confirms the hub accepts the agent

**Success output:**
```
Testing connection to hub
URL: ws://192.168.1.100:8080/ws/agent

1. Checking websockets module...
✓ websockets module available
2. Resolving hostname 192.168.1.100...
✓ DNS resolved to 192.168.1.100
3. Testing TCP connection to 192.168.1.100:8080...
✓ TCP connection successful
4. Skipping TLS check (using ws://)
5. Testing WebSocket connection and authentication...
✓ WebSocket connection successful
✓ Agent registration successful

All tests passed!

Agent ID: a1b2c3d4-...
Project: my-project
API Key: ****configured
```

**Failure example (authentication):**
```
5. Testing WebSocket connection and authentication...
✗ Authentication failed (403 Forbidden) - check API key

Troubleshooting hints:
  • Check that HUB_API_KEY on server matches api_key in config
  • Verify api_key is set in .galangal/config.yaml:
    hub:
      api_key: your-api-key
```

**Failure example (connection refused):**
```
3. Testing TCP connection to 192.168.1.100:8080...
✗ TCP connection refused
  Hub server may not be running on 192.168.1.100:8080
```

### galangal hub info

Show hub server URLs:

```bash
galangal hub info
```

Output:
```
Hub URL: http://192.168.1.100:8080

Dashboard: http://192.168.1.100:8080/
API: http://192.168.1.100:8080/api/
WebSocket: ws://192.168.1.100:8080/ws/agent
```

## Connection Behavior

### Automatic Connection

When hub is enabled, galangal automatically:

1. Connects to hub at workflow start
2. Sends state updates on every stage change
3. Sends heartbeats every 30 seconds
4. Reconnects automatically if disconnected

### Graceful Degradation

Hub connection is optional. If the hub is unavailable:

- Workflows continue normally
- State updates are skipped
- Warning is logged (in debug mode)

### Events Sent to Hub

| Event | When |
|-------|------|
| `register` | Agent connects |
| `state_update` | Stage changes, approval needed |
| `stage_start` | Stage begins |
| `stage_complete` | Stage succeeds |
| `stage_fail` | Stage fails |
| `approval_needed` | Waiting for approval |
| `rollback` | Rolling back to earlier stage |
| `task_complete` | Workflow finishes |

## Security Considerations

### API Key

- Generate with: `openssl rand -hex 32`
- Store securely (not in version control)
- Rotate periodically

### Network

- Use HTTPS/WSS in production
- Consider Tailscale for private access
- Firewall hub to trusted IPs if possible

### Data

- Hub stores task names, stages, timing
- Does not store code or full artifacts
- SQLite database can be backed up/encrypted
