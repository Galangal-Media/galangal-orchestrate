# Hub Deployment

This guide covers deploying Galangal Hub on your server.

## Docker Image

The official image is published to GitHub Container Registry:

```
ghcr.io/galangal-media/galangal-hub:latest
```

### Available Tags

| Tag | Description |
|-----|-------------|
| `latest` | Most recent stable build |
| `v1.0.0` | Specific version |
| `sha-abc1234` | Specific commit |

## Deployment Options

### Option 1: Simple Docker Run

```bash
docker run -d \
  --name galangal-hub \
  --restart unless-stopped \
  -p 8080:8080 \
  -v galangal-hub-data:/data \
  ghcr.io/galangal-media/galangal-hub:latest
```

### Option 2: Docker Compose

Create a `docker-compose.yml`:

```yaml
version: '3.8'

services:
  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    container_name: galangal-hub
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - galangal-hub-data:/data
    environment:
      - HUB_HOST=0.0.0.0
      - HUB_PORT=8080

volumes:
  galangal-hub-data:
```

Run:

```bash
docker-compose up -d
```

### Option 3: Add to Existing Docker Compose

If you already have a Docker Compose setup (e.g., media server with Plex, Sonarr, etc.), add galangal-hub as another service.

**Important:** Check for port conflicts. If another service uses port 8080, map to a different host port.

Add to your existing `docker-compose.yml`:

```yaml
  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    container_name: galangal-hub
    environment:
      - TZ=Europe/London
      - HUB_USERNAME=admin
      - HUB_PASSWORD=your-secure-password
      - HUB_API_KEY=your-agent-api-key
    volumes:
      - /home/docker/galangal-hub/data:/data
    ports:
      - 8081:8080  # Use 8081 if 8080 is taken
    restart: unless-stopped
```

Start the service:

```bash
docker-compose up -d galangal-hub
```

The data directory is created automatically with correct permissions.

Configure your development machine:

```yaml
# .galangal/config.yaml
hub:
  enabled: true
  url: ws://your-server-ip:8081/ws/agent
  api_key: your-agent-api-key  # Must match HUB_API_KEY on server
```

#### With Cloudflare Tunnel

If you use Cloudflare Tunnel (cloudflared) for remote access, add a public hostname in your Cloudflare Zero Trust dashboard:

1. Go to **Access** → **Tunnels** → your tunnel → **Public Hostname**
2. Add hostname:
   - Subdomain: `galangal` (or your choice)
   - Domain: your domain
   - Service: `http://galangal-hub:8080`

Then configure agents to use the public URL:

```yaml
# .galangal/config.yaml
hub:
  enabled: true
  url: wss://galangal.yourdomain.com/ws/agent
  api_key: your-agent-api-key  # Must match HUB_API_KEY on server
```

Note: Use `wss://` (secure WebSocket) when going through Cloudflare.

### Option 4: Tailscale (Secure, No Port Forwarding)

For secure access without exposing ports:

```yaml
version: '3.8'

services:
  tailscale:
    image: tailscale/tailscale:latest
    hostname: galangal-hub
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    volumes:
      - tailscale-state:/var/lib/tailscale
      - /dev/net/tun:/dev/net/tun
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale

  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    network_mode: "service:tailscale"
    volumes:
      - galangal-hub-data:/data
    depends_on:
      - tailscale

volumes:
  galangal-hub-data:
  tailscale-state:
```

Get a Tailscale auth key from https://login.tailscale.com/admin/settings/keys

```bash
export TS_AUTHKEY=tskey-auth-xxxxx
docker-compose up -d
```

Access via: `https://galangal-hub` (from your Tailnet)

### Option 5: Behind Reverse Proxy (Traefik)

Add labels to your container:

```yaml
services:
  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.galangal-hub.rule=Host(`hub.yourdomain.com`)"
      - "traefik.http.routers.galangal-hub.entrypoints=websecure"
      - "traefik.http.routers.galangal-hub.tls.certresolver=letsencrypt"
      - "traefik.http.services.galangal-hub.loadbalancer.server.port=8080"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_HOST` | `0.0.0.0` | Host to bind to |
| `HUB_PORT` | `8080` | Port to listen on |
| `HUB_DB_PATH` | `/data/hub.db` | SQLite database path |
| `HUB_API_KEY` | (none) | API key for agent WebSocket connections |
| `HUB_USERNAME` | (none) | Dashboard login username |
| `HUB_PASSWORD` | (none) | Dashboard login password |

## Authentication

### Dashboard Login (Username/Password)

To require login for the web dashboard:

```yaml
environment:
  - HUB_USERNAME=admin
  - HUB_PASSWORD=your-secure-password
```

When enabled:
- Visiting the dashboard redirects to `/login`
- Enter username/password to access
- Session lasts 7 days
- Logout via `/logout` or the logout link in the nav

### Agent API Key

To require API key for agent connections:

```bash
# Generate a key
openssl rand -hex 32
```

```yaml
# docker-compose.yml
environment:
  - HUB_API_KEY=your-generated-key
```

Agents must include the key:

```yaml
# .galangal/config.yaml
hub:
  enabled: true
  url: ws://your-server:8080/ws/agent
  api_key: your-generated-key
```

### Full Authentication Example

Both dashboard login and agent API key:

```yaml
services:
  galangal-hub:
    image: ghcr.io/galangal-media/galangal-hub:latest
    environment:
      - HUB_USERNAME=admin
      - HUB_PASSWORD=dashboard-password
      - HUB_API_KEY=agent-api-key
    volumes:
      - galangal-hub-data:/data
    ports:
      - "8080:8080"
```

## Maintenance

### View Logs

```bash
docker logs -f galangal-hub
```

### Update

```bash
docker-compose pull
docker-compose up -d
```

### Backup Database

```bash
docker cp galangal-hub:/data/hub.db ./backup-$(date +%Y%m%d).db
```

### Health Check

```bash
curl http://localhost:8080/
```

## Resource Requirements

- **CPU**: 0.25-1 core
- **Memory**: 128-512 MB
- **Disk**: ~100 MB for image, database grows with usage

## Troubleshooting

### Test Connection from Agent

Run the diagnostic command from your development machine:

```bash
galangal hub test
```

This performs step-by-step testing and provides specific error messages:
- DNS resolution
- TCP connectivity
- TLS handshake (for wss://)
- WebSocket authentication
- Agent registration

See [Configuration - CLI Commands](configuration.md#galangal-hub-test) for detailed output examples.

### Container Won't Start

```bash
docker logs galangal-hub
```

### Agents Can't Connect

1. Run `galangal hub test` to identify the issue
2. Check firewall allows the hub port (default 8080)
3. Verify WebSocket URL includes `/ws/agent`
4. Check API key matches (if `HUB_API_KEY` is set on server)

**Common errors from `galangal hub test`:**

| Error | Cause | Solution |
|-------|-------|----------|
| DNS resolution failed | Hostname not reachable | Check hostname/IP is correct |
| TCP connection refused | Hub not running | Start the container |
| TCP connection timed out | Firewall blocking | Open port in firewall |
| 403 Forbidden | API key mismatch | Check `api_key` matches `HUB_API_KEY` |
| 404 Not Found | Wrong URL path | Use `/ws/agent` path |

### Database Locked

SQLite can lock if multiple processes access it. Ensure only one container runs.
