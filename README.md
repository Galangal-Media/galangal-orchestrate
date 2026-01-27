# Galangal Orchestrate

**Turn AI coding assistants into structured development workflows.**

Galangal wraps [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) to execute a deterministic, multi-stage development pipeline with approval gates, validation, and automatic rollback.

## Why Use This?

Instead of open-ended AI coding sessions, you get a structured workflow:

1. **PM** - AI writes requirements, you approve before code is written
2. **Design** - AI proposes architecture, you approve the approach
3. **Dev** - AI implements according to approved specs
4. **Test/QA/Review** - Automated validation with rollback on failure
5. **Docs** - AI updates documentation

If anything fails, the workflow rolls back with context about what went wrong.

## Quick Start

```bash
# Install
pip install galangal-orchestrate

# Initialize in your project
cd your-project
galangal init

# Start a task
galangal start "Add user authentication with JWT"

# Check status / resume
galangal status
galangal resume
```

## Requirements

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (`claude` command)
- Git

## Commands

| Command | Description |
|---------|-------------|
| `galangal init` | Initialize in current project |
| `galangal start "desc"` | Start new task |
| `galangal status` | Show task status |
| `galangal resume` | Continue active task |
| `galangal list` | List all tasks |
| `galangal complete` | Finalize & create PR |

**Interactive controls during execution:**
- `^Q` Quit/pause
- `^I` Interrupt with feedback
- `^N` Skip stage
- `^B` Go back
- `^E` Pause for manual edit

## Galangal Hub

Monitor and control workflows remotely across multiple machines.

```bash
# Deploy hub server (Docker)
docker run -d -p 8080:8080 \
  -e HUB_USERNAME=admin \
  -e HUB_PASSWORD=your-password \
  -e HUB_API_KEY=your-api-key \
  -v galangal-hub-data:/data \
  ghcr.io/galangal-media/galangal-hub:latest
```

```yaml
# Enable in your project (.galangal/config.yaml)
hub:
  enabled: true
  url: ws://your-server:8080/ws/agent
  api_key: your-api-key  # Must match HUB_API_KEY on server
```

See [Hub Documentation](docs/hub/README.md) for full setup instructions.

## Documentation

| Topic | Link |
|-------|------|
| **Getting Started** | [docs/getting-started.md](docs/getting-started.md) |
| **Configuration** | [docs/local-development/configuration.md](docs/local-development/configuration.md) |
| **Workflow Stages** | [docs/local-development/workflow-pipeline.md](docs/local-development/workflow-pipeline.md) |
| **Hub (Remote Control)** | [docs/hub/README.md](docs/hub/README.md) |
| **GitHub Integration** | [docs/github-integration.md](docs/github-integration.md) |
| **Troubleshooting** | [docs/troubleshooting.md](docs/troubleshooting.md) |
| **Architecture** | [docs/local-development/architecture.md](docs/local-development/architecture.md) |

## Task Types

| Type | Stages | Use Case |
|------|--------|----------|
| **Feature** | Full workflow | New functionality |
| **Bug Fix** | PM → DEV → TEST → QA → REVIEW | Fixing bugs |
| **Refactor** | PM → DESIGN → DEV → TEST → REVIEW | Code restructuring |
| **Chore** | PM → DEV → TEST → REVIEW | Config, dependencies |
| **Docs** | PM → DOCS | Documentation only |
| **Hotfix** | PM → DEV → TEST | Critical fixes |

## License

MIT License - see LICENSE file.
