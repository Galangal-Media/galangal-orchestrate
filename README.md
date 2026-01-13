# Galangal Orchestrate

AI-driven development workflow orchestrator. A deterministic workflow system that guides AI assistants through structured development stages.

**Note:** Currently designed for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with a Claude Pro or Max subscription. Support for other AI backends (Gemini, etc.) is planned for future releases.

## Features

- **Structured Workflow**: PM → DESIGN → DEV → TEST → QA → SECURITY → REVIEW → DOCS
- **Smart Stage Planning**: PM analyzes tasks and recommends which stages to run/skip
- **Interactive Controls**: Skip stages (^N), go back (^B), pause for edits (^E), interrupt with feedback (^I)
- **Task Type Templates**: Optimized workflows for features, bugfixes, hotfixes, docs, etc.
- **Multi-Framework Support**: Python, TypeScript, PHP, Go, Rust - configure multiple stacks per project
- **Config-Driven**: All validation, prompts, and behavior customizable via YAML
- **AI Backend Abstraction**: Built for Claude CLI, ready for Gemini and others
- **Approval Gates**: Human-in-the-loop for plans and designs
- **Automatic Rollback**: Failed stages roll back to appropriate fix points
- **TUI Progress Display**: Real-time progress visualization with dynamic stage updates

## Installation

```bash
pip install galangal-orchestrate
```

Or with pipx for isolated global install (recommended):

```bash
pipx install galangal-orchestrate
```

### Updating

```bash
# If installed with pip
pip install --upgrade galangal-orchestrate

# If installed with pipx
pipx upgrade galangal-orchestrate
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

Different task types have optimized stage flows:

| Type | Stage Flow | Use Case |
|------|------------|----------|
| Feature | Full workflow | New functionality |
| Bug Fix | PM → DEV → TEST → QA | Fix with regression check |
| Refactor | PM → DESIGN → DEV → TEST | Code restructuring |
| Chore | PM → DEV → TEST | Dependencies, config, tooling |
| Docs | PM → DOCS | Documentation only |
| Hotfix | PM → DEV → TEST | Critical expedited fix |

The PM stage can further refine which stages run based on task analysis (see [PM-driven Stage Planning](#pm-driven-stage-planning)).

## Interactive Controls

During workflow execution, use these keybindings:

| Key | Action | Description |
|-----|--------|-------------|
| `^Q` | Quit | Pause and exit workflow |
| `^I` | Interrupt | Stop current stage, provide feedback, rollback to DEV |
| `^N` | Skip | Skip current stage, advance to next |
| `^B` | Back | Go back to previous stage |
| `^E` | Edit | Pause for manual editing, press Enter to resume |

### Interrupt with Feedback (^I)

When you see something going wrong mid-stage:
1. Press `^I` to interrupt
2. Enter feedback describing what needs to be fixed
3. Workflow rolls back to DEV with your feedback in context
4. A `ROLLBACK.md` artifact is created for the AI to reference

### Manual Edit Pause (^E)

Need to make a quick manual fix?
1. Press `^E` to pause
2. Make your edits in your editor
3. Press Enter to resume the current stage

## PM-driven Stage Planning

After the PM stage analyzes your task, it outputs a `STAGE_PLAN.md` artifact recommending which optional stages to run or skip:

```markdown
# Stage Plan

## Recommendations
| Stage | Action | Reason |
|-------|--------|--------|
| MIGRATION | skip | No database changes detected |
| CONTRACT | skip | Internal refactor, no API changes |
| SECURITY | run | Handling user authentication input |
| BENCHMARK | skip | UI-only changes, no performance impact |
```

This allows the AI to make intelligent decisions about which stages are relevant based on the actual task content, rather than relying solely on task type defaults.

### Stage Preview

After plan approval, you'll see a preview of the workflow:

```
Workflow Preview

Stages to run:
  PM → DESIGN → DEV → TEST → QA → DOCS

Skipping:
  MIGRATION, CONTRACT, BENCHMARK, SECURITY

Controls during execution:
  ^N Skip stage  ^B Back  ^E Pause for edit  ^I Interrupt
```

The progress bar dynamically updates to show only relevant stages.

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
    timeout: 3600
    commands:
      - name: "Lint"
        command: "./scripts/lint.sh"
        timeout: 600
      - name: "Tests"
        command: "pytest"

pr:
  codex_review: true
  base_branch: main

logging:
  enabled: true
  level: info
  file: logs/galangal.jsonl
  json_format: true
  console: false

prompt_context: |
  ## Project Patterns
  - Use repository pattern for data access
  - API responses use api_success() / api_error()
```

### Approver Name

Configure your name to auto-fill approval signoffs:

```yaml
project:
  name: "My Project"
  approver_name: "Jane Smith"  # Auto-fills in plan/design approvals
```

When set, this name is used as the default when approving plans and designs, saving you from typing it each time.

### New in v0.2.22: Structured Logging

If you're upgrading from an earlier version, you can add the optional `logging` section to your existing `config.yaml`:

```yaml
# Add to .galangal/config.yaml
logging:
  enabled: true           # Enable structured logging
  level: info             # debug, info, warning, error
  file: logs/galangal.jsonl  # Log file path (JSON Lines format)
  json_format: true       # JSON output (false for pretty console)
  console: false          # Also output to stderr
```

When enabled, logs workflow events like `stage_started`, `stage_completed`, `rollback`, etc. in JSON format for easy parsing and aggregation.

## Customizing Prompts

Galangal uses a layered prompt system:

1. **Base prompts** - Generic, language-agnostic prompts built into the package
2. **Project prompts** - Your customizations in `.galangal/prompts/`

### Prompt Modes

Project prompts support two modes:

#### Supplement Mode (Recommended)

Add project-specific content that gets prepended to the base prompt. Include the `# BASE` marker where you want the base prompt inserted:

```markdown
<!-- .galangal/prompts/dev.md -->

## My Project CLI Scripts

Use these commands for testing:
- `./scripts/test.sh` - Run tests
- `./scripts/lint.sh` - Run linter

## My Project Patterns

- Always use `api_success()` for responses
- Never use raw SQL queries

# BASE
```

The `# BASE` marker tells galangal to insert the generic base prompt at that location. Your project-specific content appears first, followed by the standard instructions.

#### Override Mode

To completely replace a base prompt, simply omit the `# BASE` marker:

```markdown
<!-- .galangal/prompts/preflight.md -->

# Custom Preflight

This completely replaces the default preflight prompt.

[Your custom instructions here...]
```

### Available Prompts

Create any of these files in `.galangal/prompts/` to customize:

| File | Stage |
|------|-------|
| `pm.md` | Requirements & planning |
| `design.md` | Architecture design |
| `preflight.md` | Environment checks |
| `dev.md` | Implementation |
| `test.md` | Test writing |
| `qa.md` | Quality assurance |
| `security.md` | Security review |
| `review.md` | Code review |
| `docs.md` | Documentation |

### Config-Based Context

You can also inject context via `config.yaml` without creating prompt files:

```yaml
# .galangal/config.yaml

# Injected into ALL stage prompts
prompt_context: |
  ## Project Rules
  - Use TypeScript strict mode
  - All APIs must be documented

# Injected into specific stages only
stage_context:
  dev: |
    ## Dev Environment
    - Run `npm run dev` for hot reload
  test: |
    ## Test Setup
    - Use vitest for unit tests
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
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed (`claude` command available)
- Claude Pro or Max subscription
- Git

## License

MIT License - see LICENSE file.
