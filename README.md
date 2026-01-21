# Galangal Orchestrate

**Turn AI coding assistants into structured development workflows.**

Galangal Orchestrate wraps [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI to execute a deterministic, multi-stage development pipeline. Instead of open-ended AI coding sessions, you get a structured workflow with approval gates, validation, and automatic rollback.

## Why Use This?

When you ask an AI to "add user authentication", you get whatever the AI decides to build. With Galangal:

1. **PM Stage** - AI writes requirements, you approve before any code is written
2. **Design Stage** - AI proposes architecture, you approve the approach
3. **Dev Stage** - AI implements according to approved specs
4. **Test Stage** - AI writes tests, validation ensures they pass
5. **QA Stage** - AI verifies requirements are met
6. **Review Stage** - AI reviews its own code for issues
7. **Docs Stage** - AI updates documentation

If anything fails, the workflow automatically rolls back to the appropriate fix point with context about what went wrong.

## Requirements

- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed (`claude` command available)
- Claude Pro or Max subscription
- Git

## Installation

```bash
# With pip
pip install galangal-orchestrate

# With pipx (recommended for CLI tools)
pipx install galangal-orchestrate
```

## Quick Start

```bash
# Initialize in your project
cd your-project
galangal init

# Start a task
galangal start "Add user authentication with JWT tokens"

# Resume after a break
galangal resume

# Check current status
galangal status
```

## Workflow Stages

| Stage | Purpose | Output |
|-------|---------|--------|
| **PM** | Requirements & planning | SPEC.md, PLAN.md, STAGE_PLAN.md |
| **DESIGN** | Architecture design | DESIGN.md |
| **PREFLIGHT** | Environment validation | PREFLIGHT_REPORT.md |
| **DEV** | Implementation | Code changes |
| **MIGRATION*** | Database migration checks | MIGRATION_REPORT.md |
| **TEST** | Test implementation | TEST_PLAN.md, TEST_SUMMARY.md |
| **TEST_GATE*** | Verify configured test suites pass | TEST_GATE_RESULTS.md |
| **CONTRACT*** | API contract validation | CONTRACT_REPORT.md |
| **QA** | Quality assurance | QA_REPORT.md |
| **BENCHMARK*** | Performance validation | BENCHMARK_REPORT.md |
| **SECURITY** | Security review | SECURITY_CHECKLIST.md |
| **REVIEW** | Code review | REVIEW_NOTES.md |
| **DOCS** | Documentation | DOCS_REPORT.md |

*Conditional stages - skipped automatically if not relevant

### Validation Artifacts

When validation commands run (tests, linters, etc.), Galangal creates debugging artifacts:

- **VALIDATION_REPORT.md** - Full output from all validation commands, useful for debugging failures
- **TEST_SUMMARY.md** - Concise test results (pass/fail counts, failed test names, coverage) included in downstream stage prompts

These artifacts help you understand what failed without digging through logs, and give downstream stages (QA, REVIEW) context about test results without bloating prompts with verbose output.

### Test Gate

The **TEST_GATE** stage is an optional quality gate that runs configured test suites mechanically (no AI). It runs after the TEST stage and before QA. All configured tests must pass for the workflow to proceed.

**Why use Test Gate?**
- Ensures specific test suites always pass before QA
- Separates "writing tests" (TEST stage) from "verifying tests pass" (TEST_GATE)
- QA can skip running automated tests and focus on exploratory testing
- Provides a clear, repeatable verification step

**Configuration:**

```yaml
# .galangal/config.yaml
test_gate:
  enabled: true
  fail_fast: true  # Stop on first failure (default: true)
  tests:
    - name: "unit tests"
      command: "npm test"
      timeout: 300  # Optional, defaults to 5 minutes
    - name: "integration tests"
      command: "pytest tests/integration -v"
    - name: "e2e tests"
      command: "cd frontend && npm run e2e"
      timeout: 600  # 10 minutes for slower tests
```

**Behavior:**
- Runs each test command in sequence
- Creates `TEST_GATE_RESULTS.md` with detailed output
- On success: proceeds to CONTRACT/QA stages
- On failure: rolls back to DEV with context about which tests failed
- QA prompt is automatically updated to skip re-running these tests

**Skip conditions:**
- `test_gate.enabled: false` (default)
- No tests configured in `test_gate.tests`
- DOCS task type (no code changes)
- Manual skip artifact (`TEST_GATE_SKIP.md`)

## Task Types

Choose the right workflow for your task:

| Type | Stages | When to Use |
|------|--------|-------------|
| **Feature** | All stages | New functionality |
| **Bug Fix** | PM → PREFLIGHT → DEV → TEST → TEST_GATE → QA | Fixing bugs |
| **Refactor** | PM → DESIGN → PREFLIGHT → DEV → TEST → TEST_GATE | Code restructuring |
| **Chore** | PM → PREFLIGHT → DEV → TEST → TEST_GATE | Config, dependencies |
| **Docs** | PM → DOCS | Documentation only |
| **Hotfix** | PM → DEV → TEST → TEST_GATE | Critical fixes |

The PM stage can further customize which stages run based on task analysis.

## Interactive Controls

During workflow execution:

| Key | Action | Description |
|-----|--------|-------------|
| `^Q` | Quit | Pause and exit (resume later with `galangal resume`) |
| `^I` | Interrupt | Stop current stage, give feedback, rollback to DEV |
| `^N` | Skip | Skip current stage, advance to next |
| `^B` | Back | Go back to previous stage |
| `^E` | Edit | Pause for manual editing, press Enter to resume |

### Interrupt with Feedback (^I)

When you see the AI doing something wrong mid-stage:
1. Press `^I` to interrupt immediately
2. Enter feedback describing what needs to be fixed
3. Workflow rolls back to DEV with your feedback as context
4. A `ROLLBACK.md` artifact is created for the AI to reference

### Manual Edit Pause (^E)

Need to make a quick fix yourself?
1. Press `^E` to pause
2. Make edits in your editor
3. Press Enter to resume the current stage

## PM-driven Stage Planning

After analyzing your task, the PM stage outputs a `STAGE_PLAN.md` recommending which optional stages to run or skip:

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

The progress bar updates dynamically to show only relevant stages.

### Workflow Preview

After PM approval, you'll see a preview showing exactly which stages will run and why others are skipped:

```
Workflow Preview

Stages to run:
  PM → DESIGN → PREFLIGHT → DEV → TEST → QA → REVIEW → DOCS

Skipping:
  MIGRATION (no files match: **/migrations/*)
  CONTRACT (no files match: **/api/*, **/openapi.*)
  BENCHMARK (task type: bug_fix)
  SECURITY (PM: simple UI change, no security impact)

Controls during execution:
  ^N Skip stage  ^B Back  ^E Pause for edit  ^I Interrupt
```

Skip reasons include:
- **Task type** - Based on the workflow template (e.g., bug fixes skip DESIGN)
- **Config** - Stages listed in `stages.skip` configuration
- **PM recommendation** - From STAGE_PLAN.md analysis
- **skip_if condition** - No changed files match the glob pattern

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
| `galangal github setup` | Set up GitHub integration |
| `galangal github issues` | List galangal-labeled issues |
| `galangal github run` | Process issues automatically |

## GitHub Integration

Galangal can create tasks directly from GitHub issues, automatically downloading screenshots and inferring task types from labels.

### Quick Setup

```bash
# 1. Install GitHub CLI (if not already installed)
# macOS:
brew install gh

# Windows:
winget install GitHub.cli

# Linux: See https://cli.github.com

# 2. Authenticate
gh auth login

# 3. Set up GitHub integration (creates labels)
galangal github setup
```

### How It Works

1. Add the `galangal` label to any GitHub issue you want to work on
2. Run `galangal start` and select "GitHub issue" as the task source
3. Galangal will:
   - Download any screenshots from the issue body
   - Infer the task type from issue labels
   - Create a task linked to the issue
   - Mark the issue as "in-progress"

When you complete the task with `galangal complete`, a PR is created that automatically closes the linked issue.

### Batch Processing

Process all galangal-labeled issues automatically:

```bash
# List issues that would be processed
galangal github run --dry-run

# Process all issues headlessly
galangal github run
```

### Issue Screenshots

Screenshots embedded in GitHub issues (using `![](url)` syntax) are automatically:
- Downloaded to `galangal-tasks/<task>/screenshots/`
- Passed to the AI during PM, Design, and Dev stages
- Available for the AI to view using Claude's Read tool

This is especially useful for bug reports with screenshots or design mockups.

### Label Configuration

Galangal maps GitHub labels to task types. The defaults are:

| Task Type | Labels |
|-----------|--------|
| bug_fix | `bug`, `bugfix` |
| feature | `enhancement`, `feature` |
| docs | `documentation`, `docs` |
| refactor | `refactor` |
| chore | `chore`, `maintenance` |
| hotfix | `hotfix`, `critical` |

Customize in `.galangal/config.yaml`:

```yaml
github:
  # Label that triggers galangal to pick up issues
  pickup_label: galangal

  # Label added when work starts
  in_progress_label: in-progress

  # Custom label colors (hex without #)
  label_colors:
    galangal: "7C3AED"
    in-progress: "FCD34D"

  # Map your labels to task types
  label_mapping:
    bug:
      - bug
      - bugfix
      - defect           # Add your custom labels
    feature:
      - enhancement
      - feature
      - new-feature
    docs:
      - documentation
      - docs
    refactor:
      - refactor
      - tech-debt
    chore:
      - chore
      - maintenance
      - dependencies
    hotfix:
      - hotfix
      - critical
      - urgent
```

### GitHub Commands

| Command | Description |
|---------|-------------|
| `galangal github setup` | Create required labels, show setup instructions |
| `galangal github setup --help-install` | Show detailed gh CLI installation instructions |
| `galangal github check` | Verify gh CLI installation and authentication |
| `galangal github issues` | List issues with galangal label |
| `galangal github issues --label <name>` | List issues with custom label |
| `galangal github run` | Process all labeled issues headlessly |
| `galangal github run --dry-run` | Preview without processing |

## Configuration

After `galangal init`, customize `.galangal/config.yaml`. Here's a complete reference:

```yaml
# =============================================================================
# PROJECT CONFIGURATION
# =============================================================================
project:
  # Project name (displayed in logs and prompts)
  name: "My Project"

  # Default approver name for plan/design approvals (auto-fills signoff prompts)
  approver_name: "Jane Smith"

  # Technology stacks in your project
  # Helps AI understand your codebase structure
  stacks:
    - language: python
      framework: fastapi       # Optional: framework name
      root: backend/           # Optional: subdirectory for this stack
    - language: typescript
      framework: vite
      root: frontend/

# =============================================================================
# TASK STORAGE
# =============================================================================
# Directory where task state and artifacts are stored
tasks_dir: galangal-tasks

# Git branch naming pattern ({task_name} is replaced with sanitized task name)
branch_pattern: "task/{task_name}"

# =============================================================================
# STAGE CONFIGURATION
# =============================================================================
stages:
  # Stages to always skip (regardless of task type or PM recommendations)
  skip:
    - BENCHMARK
    - CONTRACT

  # Default timeout for each stage in seconds (4 hours default)
  timeout: 14400

  # Maximum retries per stage before rollback (default: 5)
  max_retries: 5

# =============================================================================
# TEST GATE CONFIGURATION
# Mechanical test verification stage (no AI) - runs after TEST, before QA
# =============================================================================
test_gate:
  # Enable the test gate stage (default: false)
  enabled: true

  # Stop on first test failure instead of running all tests (default: true)
  fail_fast: true

  # Test suites to run - all must pass for the stage to succeed
  tests:
    - name: "unit tests"
      command: "npm test"
      timeout: 300           # Timeout in seconds (default: 300)
    - name: "integration tests"
      command: "pytest tests/integration -v"
    - name: "e2e tests"
      command: "cd frontend && npm run e2e"
      timeout: 600           # Longer timeout for e2e tests

# =============================================================================
# VALIDATION CONFIGURATION
# Each stage can have validation commands, checks, and skip conditions
# =============================================================================
validation:
  # Preflight checks run before DEV stage
  preflight:
    timeout: 300  # Timeout for each check in seconds
    checks:
      - name: "Git status clean"
        command: "git status --porcelain"
        expect_empty: true      # Pass if output is empty
        warn_only: false        # If true, warn but don't fail
      - name: "Node modules exist"
        path_exists: "node_modules"  # Check if path exists
      - name: "Dependencies installed"
        command: "npm ls --depth=0"
        warn_only: true

  # Migration stage validation
  migration:
    # Skip if no migration files changed
    skip_if:
      no_files_match:
        - "migrations/**"
        - "**/migrations/**"
        - "alembic/**"
    timeout: 600
    commands:
      - name: "Run migrations"
        command: "python manage.py migrate --check"
        timeout: 300           # Override timeout for this command
        optional: false        # If true, don't fail if command fails
        allow_failure: false   # If true, report but don't block

  # Test stage validation
  test:
    timeout: 600
    commands:
      - name: "Unit tests"
        command: "pytest tests/unit"
      - name: "Integration tests"
        command: "pytest tests/integration"
        optional: true         # Don't fail if integration tests missing
      # Use array form for paths with spaces or special characters
      - name: "Task-specific tests"
        command: ["pytest", "{task_dir}/tests"]  # {task_dir} is substituted

  # Contract stage (API compatibility)
  contract:
    skip_if:
      no_files_match: "openapi.yaml"
    timeout: 300
    commands:
      - name: "Validate OpenAPI spec"
        command: "openapi-spec-validator openapi.yaml"

  # QA stage validation
  qa:
    timeout: 3600
    commands:
      - name: "Lint"
        command: "./scripts/lint.sh"
        timeout: 600
      - name: "Type check"
        command: "mypy src/"
        timeout: 600
    # Marker-based validation (for AI output verification)
    artifact: "QA_REPORT.md"
    pass_marker: "## PASS"
    fail_marker: "## FAIL"

  # Security stage validation
  security:
    timeout: 1800
    commands:
      - name: "Security scan"
        command: "bandit -r src/"
        allow_failure: true    # Report issues but don't block
    artifacts_required:
      - "SECURITY_CHECKLIST.md"

  # Review stage validation
  review:
    timeout: 1800
    artifact: "REVIEW_NOTES.md"
    pass_marker: "APPROVED"
    fail_marker: "REJECTED"

  # Docs stage validation
  docs:
    timeout: 900
    artifacts_required:
      - "DOCS_REPORT.md"

# =============================================================================
# AI BACKEND CONFIGURATION
# =============================================================================
ai:
  # Default backend to use
  default: claude

  # Available backends with customizable CLI flags
  backends:
    claude:
      command: claude          # CLI command to invoke
      args:                    # Arguments with {placeholder} substitution
        - "--output-format"
        - "stream-json"
        - "--verbose"
        - "--max-turns"
        - "{max_turns}"        # Replaced with max_turns value
        - "--permission-mode"
        - "bypassPermissions"
      max_turns: 200           # Maximum conversation turns per stage
      read_only: false         # If true, backend cannot write files

    codex:
      command: codex
      args:
        - "exec"
        - "--full-auto"
        - "--output-schema"
        - "{schema_file}"      # Replaced with schema file path
        - "-o"
        - "{output_file}"      # Replaced with output file path
      max_turns: 50
      read_only: true          # Codex runs in read-only sandbox

  # Use different backends for specific stages
  stage_backends:
    REVIEW: codex              # Use Codex for code review
    # QA: gemini               # Use Gemini for QA (when supported)

# =============================================================================
# DOCUMENTATION CONFIGURATION
# =============================================================================
docs:
  # Directory for changelog entries
  changelog_dir: docs/changelog

  # Directory for security audit reports
  security_audit: docs/security

  # Directory for general documentation
  general: docs

  # Toggle documentation updates
  update_changelog: true       # Update changelog in DOCS stage
  update_security_audit: true  # Create security reports in SECURITY stage
  update_general_docs: true    # Update general docs in DOCS stage

# =============================================================================
# PULL REQUEST CONFIGURATION
# =============================================================================
pr:
  # Base branch for PRs (e.g., main, develop)
  base_branch: main

  # Add @codex review to PR body for automated review
  codex_review: false

# =============================================================================
# STRUCTURED LOGGING
# =============================================================================
logging:
  # Enable structured logging to file
  enabled: true

  # Log level: debug, info, warning, error
  level: info

  # Log file path (JSON Lines format for easy parsing)
  file: logs/galangal.jsonl

  # Output format: true for JSON, false for pretty console format
  json_format: true

  # Also output to console (stderr)
  console: false

# =============================================================================
# TASK TYPE SETTINGS
# Per-task-type overrides
# =============================================================================
task_type_settings:
  bugfix:
    skip_discovery: true       # Skip the PM discovery Q&A for bugfixes
  hotfix:
    skip_discovery: true

# =============================================================================
# PROMPT CONTEXT
# Additional context injected into AI prompts
# =============================================================================

# Global context added to ALL stage prompts
prompt_context: |
  ## Project Conventions
  - Use repository pattern for data access
  - API responses use api_success() / api_error() helpers
  - All errors should be logged with context

  ## Testing Standards
  - Unit tests go in tests/unit/
  - Integration tests go in tests/integration/
  - Use pytest fixtures for test data

# Per-stage context (merged with global context)
stage_context:
  dev: |
    ## Development Environment
    - Run `npm run dev` for hot reload
    - Database: PostgreSQL on localhost:5432
    - Redis: localhost:6379

  test: |
    ## Test Setup
    - Use vitest for frontend unit tests
    - Use pytest for backend tests
    - Mock external APIs in tests

  security: |
    ## Security Requirements
    - All user input must be validated
    - Use parameterized queries (no raw SQL)
    - Secrets must use environment variables
```

## AI Backend Customization

Galangal invokes AI backends (like Claude Code CLI) using configurable commands and arguments. This allows you to customize CLI flags without modifying code.

### Default Behavior

By default, Galangal invokes Claude with:
```bash
cat prompt.txt | claude --output-format stream-json --verbose --max-turns 200 --permission-mode bypassPermissions
```

### Customizing CLI Flags

Override any flags in `.galangal/config.yaml`:

```yaml
ai:
  backends:
    claude:
      command: claude
      args:
        - "--output-format"
        - "stream-json"
        - "--verbose"
        - "--max-turns"
        - "{max_turns}"
        - "--permission-mode"
        - "bypassPermissions"
        - "--model"              # Add custom flags
        - "opus"
      max_turns: 300             # Increase max turns
```

### Placeholder Reference

Arguments can include placeholders that are substituted at runtime:

| Placeholder | Backend | Description |
|-------------|---------|-------------|
| `{max_turns}` | claude | Maximum conversation turns |
| `{schema_file}` | codex | Path to JSON schema file |
| `{output_file}` | codex | Path for structured output |

### Common Customizations

**Use a specific model:**
```yaml
ai:
  backends:
    claude:
      args:
        - "--output-format"
        - "stream-json"
        - "--model"
        - "sonnet"           # Use Sonnet instead of default
        - "--max-turns"
        - "{max_turns}"
```

**Increase turn limit for complex tasks:**
```yaml
ai:
  backends:
    claude:
      max_turns: 500         # Default is 200
      args:
        - "--output-format"
        - "stream-json"
        - "--max-turns"
        - "{max_turns}"      # Will use 500
```

**Use different backends per stage:**
```yaml
ai:
  default: claude
  stage_backends:
    REVIEW: codex            # Use Codex for code review
```

### Adding a Custom Backend

Define any CLI tool as a backend:

```yaml
ai:
  backends:
    my-backend:
      command: my-ai-tool
      args:
        - "--prompt-file"
        - "-"                # Read from stdin
        - "--json-output"
      max_turns: 100
      read_only: true        # Cannot write files directly
```

Then use it:
```yaml
ai:
  default: my-backend
  # Or per-stage:
  stage_backends:
    QA: my-backend
```

## Customizing Prompts

Galangal uses a layered prompt system:

1. **Base prompts** - Built-in, language-agnostic prompts
2. **Project prompts** - Your customizations in `.galangal/prompts/`

### Supplement Mode (Recommended)

Add project-specific content that gets prepended to the base prompt:

```markdown
<!-- .galangal/prompts/dev.md -->

## Project CLI Scripts

- `./scripts/test.sh` - Run all tests
- `./scripts/lint.sh` - Run linter

## Patterns to Follow

- Always use `api_success()` for responses
- Never use raw SQL queries

# BASE
```

The `# BASE` marker inserts the default prompt at that location.

### Override Mode

To completely replace a base prompt, omit the `# BASE` marker:

```markdown
<!-- .galangal/prompts/preflight.md -->

# Custom Preflight

This completely replaces the default preflight prompt.

[Your custom instructions...]
```

### Available Prompt Files

Create any of these in `.galangal/prompts/`:

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

## Troubleshooting

### Debug Mode

When something goes wrong and you need to see what happened:

```bash
# Enable debug logging (writes to logs/galangal_debug.log)
galangal --debug start "task description"
galangal --debug resume

# Alternative: set environment variable
GALANGAL_DEBUG=1 galangal start "task description"
```

Debug mode creates two log files:
- `logs/galangal_debug.log` - Human-readable debug trace with timestamps
- `logs/galangal.jsonl` - Structured JSON logs for programmatic analysis

**Example debug log:**
```
[14:32:15.123] GitHub integration failed: HTTPError: 401 Unauthorized
[14:32:15.124] Traceback:
  File "/path/to/start.py", line 138, in task_creation_thread
    check = ensure_github_ready()
  ...
```

### Structured Logging Configuration

Enable structured logging in `.galangal/config.yaml`:

```yaml
logging:
  enabled: true        # Enable logging
  level: debug         # debug, info, warning, error
  file: logs/galangal.jsonl
  json_format: true    # JSON for parsing, false for console format
  console: false       # Also output to stderr
```

### Tests Hang at TEST Stage

Test frameworks must run non-interactively. Common issues:

**Playwright** - HTML reporter blocks by default:
```bash
# Use non-blocking reporter
npx playwright test --reporter=list

# Or set environment variable
PLAYWRIGHT_HTML_OPEN=never npx playwright test

# Or in playwright.config.ts:
# reporter: [['html', { open: 'never' }]]
```

**Jest/Vitest** - Watch mode blocks:
```bash
# Wrong (blocks):
npm test -- --watch

# Correct:
npm test
```

**Cypress** - Interactive mode blocks:
```bash
# Wrong (blocks):
cypress open

# Correct:
cypress run
```

**General rule**: Use CI-friendly commands that exit automatically. Avoid watch mode, interactive mode, or any GUI that waits for user input.

### TEST Stage Loops Indefinitely

If the TEST stage keeps retrying instead of rolling back to DEV:
1. Ensure your TEST_PLAN.md has a clear `**Status:** PASS` or `**Status:** FAIL` line
2. If tests fail due to implementation bugs, the AI should report FAIL (not try to fix the code)
3. Check that test commands exit with proper exit codes (0 for success, non-zero for failure)

**Note:** As of v0.12.0, when artifact markers are unclear (missing PASS/FAIL), Galangal prompts you to manually approve or reject instead of retrying indefinitely. You'll see the artifact content and can make the decision yourself.

### "Galangal has not been initialized" Error

Run `galangal init` in your project root before using other commands.

### Task Exits Without Error Message

If a task quits unexpectedly with no visible error:

1. **Enable debug mode** and re-run:
   ```bash
   galangal --debug start "your task"
   ```

2. **Check the debug log** for the actual error:
   ```bash
   tail -50 logs/galangal_debug.log
   ```

3. **Common causes**:
   - GitHub authentication failed (run `gh auth status`)
   - Network timeout fetching issues
   - Missing permissions for the repository
   - Invalid issue number or no issues with `galangal` label

### GitHub Integration Fails Silently

If `galangal start` from a GitHub issue exits without creating a task:

```bash
# Check GitHub CLI is working
gh auth status
gh repo view

# Try with debug mode
galangal --debug start --issue 123
```

Check `logs/galangal_debug.log` for specific errors like:
- `401 Unauthorized` - Re-authenticate with `gh auth login`
- `404 Not Found` - Issue doesn't exist or wrong repo
- `No issues with 'galangal' label` - Add the label to an issue first

## License

MIT License - see LICENSE file.
