# Getting Started

This guide walks you through setting up Galangal and completing your first AI-driven development task.

## Prerequisites

- **Python 3.10+**
- **[Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)** — the `claude` command must be available in your PATH
- **Git** — your project must be a git repository

## Installation

```bash
pip install galangal-orchestrate
```

Verify the install:

```bash
galangal --help
```

## Project Setup

Navigate to your project root and run:

```bash
cd your-project
galangal init
```

This launches an interactive setup wizard that creates:

- `.galangal/config.yaml` — project configuration (name, tech stacks, stage settings)
- `.galangal/prompts/` — directory for custom prompt overrides (empty by default, uses built-in prompts)
- Adds `galangal-tasks/` to your `.gitignore`

For a minimal setup without the wizard, use `--quick`:

```bash
galangal init --quick
```

You can re-run `galangal init` at any time to reconfigure or add newly available settings.

## Starting Your First Task

```bash
galangal start "Add user authentication with JWT"
```

The TUI opens and walks you through task creation:

1. **Branch check** — confirms you're on the base branch (e.g., `main`), offers to switch if not
2. **Task type** — select from: Feature, Bug Fix, Refactor, Chore, Docs, or Hotfix
3. **Description** — enter a task description (or pass it as an argument like above)
4. **Branch creation** — creates a git branch for the task automatically

### Task Types

Each type runs a different subset of the pipeline stages:

| Type | Stages |
|------|--------|
| Feature | All stages |
| Bug Fix | PM → PREFLIGHT → DEV → TEST → QA → REVIEW |
| Refactor | PM → DESIGN → PREFLIGHT → DEV → TEST → REVIEW |
| Chore | PM → PREFLIGHT → DEV → TEST → REVIEW |
| Docs | PM → DOCS |
| Hotfix | PM → DEV → TEST |

You can specify the type directly:

```bash
galangal start "Fix login timeout" --type bug_fix
```

### GitHub Issues

If you have GitHub integration configured, you can start tasks directly from issues:

```bash
galangal start --issue 42
```

Or choose interactively — when you run `galangal start` without arguments, you'll be prompted to create from a description or pick from labeled GitHub issues.

## The TUI

Once the workflow starts, you'll see the Galangal TUI (terminal UI):

```
┌──────────────────────────────────────────────────────────────────┐
│ Task: my-task  Stage: DEV (1/5)  Elapsed: 2:34  Turns: 5        │
├──────────────────────────────────────────────────────────────────┤
│        ● PM ━ ● DESIGN ━ ● DEV ━ ○ TEST ━ ○ QA ━ ○ DONE         │
├────────────────────────────────────────────────┬─────────────────┤
│ Activity Log                                   │ Files           │
│ 11:30:00 • Starting stage...                   │ 📖 file.py      │
│ 11:30:01 📖 Read: file.py                      │ ✏️ test.py       │
├────────────────────────────────────────────────┴─────────────────┤
│ ⠋ Running: waiting for API response                              │
├──────────────────────────────────────────────────────────────────┤
│ ^Q Quit  ^I Interrupt  ^N Skip  ^B Back  ^E Edit                 │
└──────────────────────────────────────────────────────────────────┘
```

- **Header** — task name, current stage, attempt number, elapsed time, turn count
- **Progress bar** — visual stage progression; completed stages are filled, current is highlighted
- **Activity log** — real-time feed of what the AI is doing (reading files, writing code, running commands)
- **Files panel** — files the AI has read or modified (toggle with `Ctrl+F`)
- **Current action** — spinner showing what's happening right now
- **Footer** — available keyboard shortcuts

Toggle between compact and verbose mode with `Ctrl+D`. Verbose mode shows all tool calls and raw output.

## Interactive Controls

These keyboard shortcuts are available while the workflow runs:

| Key | Action | When to use |
|-----|--------|-------------|
| `Ctrl+Q` | Quit/pause | Save progress and exit. Resume later with `galangal resume`. |
| `Ctrl+I` | Interrupt with feedback | Stop the current stage and provide feedback. You'll be prompted for a rollback target. |
| `Ctrl+N` | Skip stage | Skip the current stage and advance to the next one. Useful for optional stages. |
| `Ctrl+B` | Go back | Return to the previous stage. Useful if you want to redo something. |
| `Ctrl+E` | Pause for manual edit | Pause the AI so you can manually edit files. Press Enter to resume. |

## Approval Gates

Two stages require your explicit approval before the workflow continues:

### PM Approval

After the PM stage generates a spec (`SPEC.md`) and plan (`PLAN.md`), you'll be asked to approve:

- **Approve** — continue to the next stage
- **Reject with feedback** — provide notes and the PM stage re-runs incorporating your feedback
- **Skip** — skip ahead without PM approval

Review the generated spec carefully. This is where you shape what the AI will build.

### Design Approval

After the DESIGN stage produces an architecture document (`DESIGN.md`), you approve similarly. This ensures you agree with the technical approach before implementation begins.

If you're away from the terminal, you can also approve from the command line:

```bash
galangal approve
galangal approve-design
```

## Handling Failures

When a stage fails validation:

1. **Automatic retry** — the stage re-runs with context about what went wrong (up to the configured `max_retries`)
2. **Rollback** — if retries are exhausted, the workflow rolls back to an appropriate earlier stage
3. **Manual intervention** — use `Ctrl+I` to interrupt, provide feedback, and guide the AI

You can also manually skip problematic stages:

```bash
galangal skip-security --reason "Internal tool only"
galangal skip-migration --reason "No database changes"
```

Or jump to a specific stage:

```bash
galangal skip-to DEV
```

## Pausing and Resuming

Press `Ctrl+Q` at any time to pause. The workflow saves its state (current stage, attempt count, all artifacts) to disk.

Resume later:

```bash
galangal resume
```

The AI picks up where it left off, with full context of what happened before the pause. For code-modifying stages (DEV, TEST, DOCS, REVIEW), it automatically checks `git status` and `git diff` to understand what changed.

Check what stage you're at:

```bash
galangal status
```

## Completing a Task

When all stages pass, the workflow completes. To finalize and create a pull request:

```bash
galangal complete --pr
```

Options:

```bash
galangal complete --pr --draft    # Create as draft PR
galangal complete --archive       # Archive task to done/ directory
galangal complete --no-archive    # Keep task in tasks directory
```

## Common Workflows

### New Feature

```bash
galangal start "Add user profiles with avatar upload"
# PM writes spec → you approve → Design → you approve → Dev → Test → QA → Review → Docs
galangal complete --pr
```

### Bug Fix

```bash
galangal start "Fix login timeout after 30 seconds" --type bug_fix
# Skips Design, Security, Benchmark — goes straight to Dev after PM
galangal complete --pr
```

### Documentation Only

```bash
galangal start "Update API docs for v2 endpoints" --type docs
# Only runs PM → Docs
galangal complete --pr
```

### Resume After Interruption

```bash
galangal status          # See where you left off
galangal resume          # Continue the workflow
```

### Switch Between Tasks

```bash
galangal list            # See all tasks
galangal switch other-task
galangal resume
```

## Next Steps

- **[Configuration](local-development/configuration.md)** — customize stage settings, validation rules, AI backends, and more
- **[Workflow Pipeline](local-development/workflow-pipeline.md)** — detailed reference for all 13 stages, rollback logic, and validation
- **[CLI Commands](local-development/cli-commands.md)** — full command reference with all options and flags
- **[Extending Galangal](local-development/extending.md)** — custom prompts, validation rules, and project-specific overrides
- **[Troubleshooting](troubleshooting.md)** — common issues and solutions
