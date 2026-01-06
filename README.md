# Galangal Orchestrate

AI-driven development workflow orchestrator. A deterministic workflow system that guides AI assistants through structured development stages.

## Features

- **Structured Workflow**: PM → DESIGN → DEV → TEST → QA → SECURITY → REVIEW → DOCS
- **Multi-Framework Support**: Python, TypeScript, PHP, Go, Rust - configure multiple stacks per project
- **Config-Driven**: All validation, prompts, and behavior customizable via YAML
- **AI Backend Abstraction**: Built for Claude CLI, ready for Gemini and others
- **Approval Gates**: Human-in-the-loop for plans and designs
- **Automatic Rollback**: Failed stages roll back to appropriate fix points
- **TUI Progress Display**: Real-time progress visualization

## Installation

```bash
pip install galangal-orchestrate
```

Or with pipx for global install:

```bash
pipx install galangal-orchestrate
```

## Quick Start

```bash
# Initialize in your project
cd your-project
galangal init

# Start a new task
galangal start "Add user authentication feature"

# Resume after a break
galangal resume

# Check status
galangal status
```

## Workflow Stages

| Stage | Purpose | Artifacts |
|-------|---------|-----------|
| PM | Requirements & planning | SPEC.md, PLAN.md |
| DESIGN | Architecture design | DESIGN.md |
| PREFLIGHT | Environment checks | PREFLIGHT_REPORT.md |
| DEV | Implementation | (code changes) |
| MIGRATION* | DB migration validation | MIGRATION_REPORT.md |
| TEST | Test implementation | TEST_PLAN.md |
| CONTRACT* | API contract validation | CONTRACT_REPORT.md |
| QA | Quality assurance | QA_REPORT.md |
| BENCHMARK* | Performance validation | BENCHMARK_REPORT.md |
| SECURITY | Security review | SECURITY_CHECKLIST.md |
| REVIEW | Code review | REVIEW_NOTES.md |
| DOCS | Documentation updates | DOCS_REPORT.md |

*Conditional stages - auto-skipped if conditions not met

## Task Types

Different task types skip certain stages:

| Type | Skips |
|------|-------|
| Feature | (full workflow) |
| Bug Fix | DESIGN, BENCHMARK |
| Refactor | DESIGN, MIGRATION, CONTRACT, BENCHMARK, SECURITY |
| Chore | DESIGN, MIGRATION, CONTRACT, BENCHMARK |
| Docs | Most stages |
| Hotfix | DESIGN, BENCHMARK |

## Configuration

After `galangal init`, customize `.galangal/config.yaml`:

```yaml
project:
  name: "My Project"
  stacks:
    - language: python
      framework: fastapi
      root: backend/
    - language: typescript
      framework: vite
      root: frontend/

stages:
  skip:
    - BENCHMARK
  timeout: 14400
  max_retries: 5

validation:
  qa:
    commands:
      - name: "Lint"
        command: "./scripts/lint.sh"
      - name: "Tests"
        command: "pytest"

pr:
  codex_review: true
  base_branch: main

prompt_context: |
  ## Project Patterns
  - Use repository pattern for data access
  - API responses use api_success() / api_error()
```

## Customizing Prompts

Export and customize stage prompts:

```bash
# Export defaults to .galangal/prompts/
galangal prompts export

# Show effective prompt for a stage
galangal prompts show dev
```

## Commands

| Command | Description |
|---------|-------------|
| `galangal init` | Initialize in current project |
| `galangal start "desc"` | Start new task |
| `galangal list` | List all tasks |
| `galangal switch <name>` | Switch active task |
| `galangal status` | Show task status |
| `galangal resume` | Continue active task |
| `galangal pause` | Pause for break |
| `galangal approve` | Approve plan |
| `galangal approve-design` | Approve design |
| `galangal skip-design` | Skip design stage |
| `galangal skip-to <stage>` | Jump to stage |
| `galangal complete` | Finalize & create PR |
| `galangal reset` | Delete active task |

## Requirements

- Python 3.10+
- Claude CLI (`claude` command available)
- Git

## License

MIT License - see LICENSE file.
