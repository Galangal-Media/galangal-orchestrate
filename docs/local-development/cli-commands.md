# CLI Commands

This document provides a reference for all Galangal CLI commands.

## Command Overview

| Category | Commands |
|----------|----------|
| **Setup** | `init` |
| **Task Management** | `start`, `list`, `switch`, `reset` |
| **Workflow Control** | `resume`, `pause`, `approve`, `approve-design` |
| **Stage Skipping** | `skip-design`, `skip-security`, `skip-migration`, `skip-contract`, `skip-benchmark`, `skip-to` |
| **Completion** | `complete` |
| **Utilities** | `status`, `prompts` |

## Setup Commands

### init

Initialize Galangal in a project:

```bash
galangal init
```

Creates:
- `.galangal/config.yaml` - Configuration file
- `.galangal/prompts/` - Prompt override directory

Options:
```bash
galangal init --force  # Overwrite existing config
```

## Task Management Commands

### start

Start a new task:

```bash
galangal start "Add user authentication"
```

Options:
```bash
galangal start "Fix login bug" --type bug_fix
galangal start "Update deps" --type chore
galangal start "Refactor auth" --type refactor
galangal start "Add docs" --type docs
galangal start "Critical fix" --type hotfix
```

Task types:
- `feature` (default) - New functionality
- `bug_fix` - Fix broken behavior
- `refactor` - Code restructuring
- `chore` - Maintenance tasks
- `docs` - Documentation only
- `hotfix` - Critical fix

### list

List all tasks:

```bash
galangal list
```

Output shows:
- Task name
- Current stage
- Status (active/paused)
- Started date

Options:
```bash
galangal list --all     # Include completed tasks
galangal list --json    # JSON output
```

### switch

Switch to a different task:

```bash
galangal switch my-other-task
```

Updates `.galangal/active_task` to the specified task.

### reset

Reset a task to start over:

```bash
galangal reset
```

Options:
```bash
galangal reset --stage PM       # Reset to specific stage
galangal reset --keep-artifacts # Keep existing artifacts
```

## Workflow Control Commands

### resume

Resume the active task:

```bash
galangal resume
```

Continues workflow from the current stage. The TUI shows:
- Stage progress
- Activity log
- Prompts for input

Options:
```bash
galangal resume --no-tui  # Use legacy console mode
```

### pause

Pause the running workflow:

Press `Ctrl+C` during execution, or:

```bash
galangal pause
```

The workflow saves state and exits gracefully.

### approve

Approve the current stage:

```bash
galangal approve
```

Used when a stage is awaiting approval (e.g., after SPEC review).

### approve-design

Approve the design stage:

```bash
galangal approve-design
```

Shortcut for design stage approval. Equivalent to running `approve` when in DESIGN stage.

## Stage Skipping Commands

### skip-design

Skip the design stage:

```bash
galangal skip-design
```

Creates `DESIGN_SKIP.md` and moves to PREFLIGHT stage.

Options:
```bash
galangal skip-design --reason "Simple bug fix"
```

### skip-security

Skip the security stage:

```bash
galangal skip-security
```

Creates `SECURITY_SKIP.md`.

Options:
```bash
galangal skip-security --reason "Internal tool only"
```

### skip-migration

Skip the migration stage:

```bash
galangal skip-migration
```

Creates `MIGRATION_SKIP.md`.

Options:
```bash
galangal skip-migration --reason "No database changes"
```

### skip-contract

Skip the contract stage:

```bash
galangal skip-contract
```

Creates `CONTRACT_SKIP.md`.

### skip-benchmark

Skip the benchmark stage:

```bash
galangal skip-benchmark
```

Creates `BENCHMARK_SKIP.md`.

### skip-to

Skip to a specific stage:

```bash
galangal skip-to DEV
galangal skip-to TEST
```

Skips all stages between current and target. Creates appropriate skip artifacts.

## Completion Commands

### complete

Complete the task and optionally create a PR:

```bash
galangal complete
```

Options:
```bash
galangal complete --pr              # Create pull request
galangal complete --pr --draft      # Create draft PR
galangal complete --archive         # Archive task to done/
galangal complete --no-archive      # Keep task in tasks dir
```

## Utility Commands

### status

Show current task status:

```bash
galangal status
```

Output:
```
Task: add-user-auth
Type: feature
Stage: DEV (attempt 2)
Status: Running

Recent Activity:
- PM completed
- DESIGN completed
- PREFLIGHT passed
- DEV in progress (retry after validation failure)
```

Options:
```bash
galangal status --json    # JSON output
galangal status --verbose # Include artifact summaries
```

### prompts

Manage and inspect prompts:

```bash
# Show a stage prompt
galangal prompts show dev

# Export all prompts
galangal prompts export ./my-prompts/

# List available prompts
galangal prompts list
```

## Command Aliases

Some commands have shorter aliases:

| Command | Alias |
|---------|-------|
| `galangal status` | `galangal st` |
| `galangal list` | `galangal ls` |
| `galangal resume` | `galangal r` |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GALANGAL_DEBUG` | Enable debug logging |
| `GALANGAL_NO_TUI` | Disable TUI mode |
| `GALANGAL_CONFIG` | Custom config file path |

Example:
```bash
GALANGAL_DEBUG=1 galangal resume
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 3 | Task not found |
| 4 | Validation failed |
| 130 | Interrupted (Ctrl+C) |

## Common Workflows

### Start and Complete a Feature

```bash
# Initialize (once per project)
galangal init

# Start the task
galangal start "Add user profiles"

# Resume and work through stages
galangal resume

# Skip optional stages if needed
galangal skip-benchmark

# Complete and create PR
galangal complete --pr
```

### Fix a Bug

```bash
galangal start "Fix login timeout" --type bug_fix
galangal resume
galangal complete --pr
```

### Resume After Pause

```bash
# Check status
galangal status

# Continue work
galangal resume
```

### Switch Between Tasks

```bash
# See all tasks
galangal list

# Switch to different task
galangal switch other-task

# Resume that task
galangal resume
```

### Reset and Restart

```bash
# Full reset
galangal reset

# Reset to specific stage
galangal reset --stage DEV
```

## Getting Help

```bash
# General help
galangal --help

# Command-specific help
galangal start --help
galangal resume --help
```

## Related Documentation

- [README](README.md) - Setup and development
- [Workflow Pipeline](workflow-pipeline.md) - Stage details
- [State Management](state-management.md) - Task state
- [Configuration](configuration.md) - Config options
