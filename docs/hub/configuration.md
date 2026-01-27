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
| `HUB_API_KEY` | (none) | API key for authentication |

### Docker Compose Example

```yaml
services:
  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    environment:
      - HUB_HOST=0.0.0.0
      - HUB_PORT=8080
      - HUB_API_KEY=${HUB_API_KEY:-}
    volumes:
      - galangal-hub-data:/data
```

### Using .env File

Create a `.env` file:

```bash
HUB_PORT=8080
HUB_API_KEY=your-secret-key
```

## CLI Commands

Check your configuration:

```bash
# Show current hub config
galangal hub status

# Test connection
galangal hub test

# Show server URLs
galangal hub info
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
