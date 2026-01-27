# Galangal Hub - Docker Deployment

Deploy the Galangal Hub server for remote monitoring and control of galangal workflows.

## Quick Start

```bash
# Pull and run (no build required)
docker-compose up -d

# View logs
docker-compose logs -f

# Access dashboard
open http://localhost:8080
```

## Image

The image is automatically built and published to GitHub Container Registry:

```
ghcr.io/galangal-media/galangal-hub:latest
```

### Available Tags

| Tag | Description |
|-----|-------------|
| `latest` | Most recent build from main branch |
| `v1.0.0` | Specific version |
| `sha-abc1234` | Specific commit |

### Pull Manually

```bash
docker pull ghcr.io/galangal-media/galangal-hub:latest
```

## Deployment Options

### Option 1: Basic (Port Exposed)

```bash
docker-compose up -d
```

- Dashboard: `http://your-server:8080`
- WebSocket: `ws://your-server:8080/ws/agent`

### Option 2: Tailscale (Secure, No Port Forwarding)

```bash
# 1. Create .env with your Tailscale auth key
cp .env.example .env
# Edit .env and set TS_AUTHKEY

# 2. Deploy
docker-compose -f docker-compose.tailscale.yml up -d

# 3. Access via Tailscale
# Dashboard: https://galangal-hub
# WebSocket: wss://galangal-hub/ws/agent
```

### Option 3: Behind Reverse Proxy (Traefik, Nginx, etc.)

Uncomment the Traefik labels in `docker-compose.yml` or configure your reverse proxy to forward to port 8080.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_VERSION` | `latest` | Docker image tag |
| `HUB_PORT` | `8080` | Port to expose on host |
| `HUB_API_KEY` | (none) | API key for authentication |
| `TS_AUTHKEY` | (required for Tailscale) | Tailscale auth key |
| `TS_HOSTNAME` | `galangal-hub` | Hostname on Tailnet |

### Using .env File

```bash
cp .env.example .env
# Edit .env with your settings
docker-compose up -d
```

## Agent Configuration

Add to each project's `.galangal/config.yaml`:

```yaml
hub:
  enabled: true
  url: ws://your-server:8080/ws/agent      # Basic deployment
  # url: wss://galangal-hub/ws/agent       # Tailscale deployment
  # api_key: your-secret-key               # If HUB_API_KEY is set
```

## Maintenance

### View Logs

```bash
docker-compose logs -f galangal-hub
```

### Update to Latest

```bash
docker-compose pull
docker-compose up -d
```

### Backup Database

```bash
# Find volume location
docker volume inspect galangal-hub-data

# Or copy from container
docker cp galangal-hub:/data/hub.db ./hub-backup.db
```

### Reset Database

```bash
docker-compose down -v  # Warning: deletes all data
docker-compose up -d
```

## Build Locally

If you need to build from source instead of using the published image:

```bash
# Edit docker-compose.yml to use build instead of image
# Then:
docker-compose build
docker-compose up -d
```

## Troubleshooting

### Container Won't Start

```bash
docker-compose logs galangal-hub
```

### Health Check Failing

```bash
# Check if server is responding
docker exec galangal-hub curl -f http://localhost:8080/
```

### Tailscale Issues

```bash
# Check Tailscale status
docker exec galangal-hub-tailscale tailscale status

# View Tailscale logs
docker-compose logs tailscale
```

### Permission Denied on /dev/net/tun

Ensure your Docker host has the `tun` module loaded:

```bash
sudo modprobe tun
```
