# Galangal Hub

Galangal Hub is a centralized dashboard for monitoring and controlling galangal workflows across multiple machines and repositories.

## Features

- **Real-time Monitoring** - See all active tasks across repos
- **Remote Approval** - Approve/reject stages from any device
- **Task History** - Track completed tasks and events
- **WebSocket Updates** - Live dashboard updates

## Quick Start

### 1. Deploy the Hub

```bash
# Using Docker (recommended)
docker run -d -p 8080:8080 \
  -v galangal-hub-data:/data \
  ghcr.io/galangal-media/galangal-hub:latest
```

Or with Docker Compose:

```bash
curl -O https://raw.githubusercontent.com/Galangal-Media/galangal-orchestrate/main/docker/docker-compose.yml
docker-compose up -d
```

### 2. Configure Your Projects

Add to each project's `.galangal/config.yaml`:

```yaml
hub:
  enabled: true
  url: ws://your-server:8080/ws/agent
```

### 3. Access the Dashboard

Open `http://your-server:8080` in your browser.

## Documentation

| Topic | Description |
|-------|-------------|
| [Deployment](deployment.md) | Docker, Tailscale, reverse proxy setup |
| [Configuration](configuration.md) | Agent and hub configuration options |
| [API Reference](api.md) | REST and WebSocket API |

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Work PC #1    │     │   Work PC #2    │     │    Laptop       │
│   (galangal)    │     │   (galangal)    │     │   (galangal)    │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │    WebSocket          │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                        ┌────────▼────────┐
                        │  Galangal Hub   │
                        │   (Server)      │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │    Browser      │
                        │   Dashboard     │
                        └─────────────────┘
```

## CLI Commands

```bash
# Check hub connection status
galangal hub status

# Test connection to hub
galangal hub test

# Show hub server URLs
galangal hub info
```
