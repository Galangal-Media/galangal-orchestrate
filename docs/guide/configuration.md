# Configuration

This document describes the Galangal configuration system, including all available options and their effects.

## Configuration Location

Configuration is stored in:

```
.galangal/config.yaml
```

## Full Configuration Schema

```yaml
# Project information
project:
  name: "My Project"
  approver_name: "Optional Approver Name"

# Git branch naming pattern ({task_name} is replaced)
branch_pattern: "task/{task_name}"

# Stage configuration
stages:
  skip: []              # Stages to always skip
  timeout: 14400        # Stage timeout in seconds (default: 4 hours)
  max_retries: 5        # Max retry attempts per stage
  commit_per_stage: true # WIP commits after code-modifying stages

# Test gate (mechanical test verification)
test_gate:
  enabled: false
  tests: []
  fail_fast: true

# Validation rules
validation:
  preflight:
    checks: []
  dev:
    commands: []
    artifact: "DEVELOPMENT.md"
    pass_marker: "COMPLETED"
  # ... other stages

# AI backend configuration
ai:
  default: "claude"
  backends:
    claude:
      command: "claude"
      args: []
      max_turns: 200
      read_only: false
  stage_backends: {}    # Per-stage backend overrides
  profile: null         # Active profile name (overrides default + stage_backends)
  profiles: {}          # Named routing profiles (see AI Profiles section)

# Peer review hook
peer_review:
  enabled: false
  backend: "codex"
  stages: ["PM", "DESIGN"]

# Pull request configuration
pr:
  codex_review: false
  base_branch: "main"

# Documentation paths
docs:
  changelog_dir: "docs/changelog"
  security_audit: "docs/security"
  general: "docs"
  update_changelog: true
  update_security_audit: true
  update_general_docs: true

# Structured logging
logging:
  enabled: false
  level: "info"
  file: null
  json_format: true
  console: false

# GitHub integration
github:
  pickup_label: "galangal"
  in_progress_label: "in-progress"
  label_mapping:
    bug: ["bug", "bugfix"]
    feature: ["enhancement", "feature"]
    # ... other mappings

# Task storage
tasks_dir: "galangal-tasks"

# Global prompt context
prompt_context: |
  Additional context for all prompts...

# Stage-specific prompt context
stage_context:
  DEV: |
    Dev-specific instructions...
  TEST: |
    Test-specific instructions...

# Per-task-type settings
task_type_settings:
  bug_fix:
    skip_discovery: true

# Artifact context filtering (optional)
artifact_context: null  # Set per-stage artifact include/exclude rules

# Artifact lineage tracking (optional)
lineage:
  enabled: false
  block_on_staleness: true

# Hub connection (see Hub docs for details)
hub:
  enabled: false
  url: "ws://localhost:8080/ws/agent"
  api_key: null
```

## Configuration Sections

### project

Project metadata:

```yaml
project:
  name: "My Project"
  approver_name: "Lead Developer"
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Project display name |
| `approver_name` | string | Name shown in approval prompts |

### stages

Workflow stage configuration:

```yaml
stages:
  skip:
    - BENCHMARK
    - CONTRACT
  timeout: 14400
  max_retries: 5
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `skip` | list | `[]` | Stages to always skip |
| `timeout` | int | `14400` | Stage timeout (seconds) |
| `max_retries` | int | `5` | Max retries per stage |
| `commit_per_stage` | bool | `true` | Create WIP commits after code-modifying stages, squash at finalization |

Valid stages to skip:
- `DESIGN`, `PREFLIGHT`, `MIGRATION`, `TEST`
- `CONTRACT`, `QA`, `BENCHMARK`
- `SECURITY`, `REVIEW`, `DOCS`

Note: `PM`, `DEV`, and `COMPLETE` cannot be skipped.

### validation

Per-stage validation rules. See [Validation System](../local-development/validation-system.md) for details.

```yaml
validation:
  preflight:
    checks:
      - name: "Python available"
        type: command
        command: "python --version"

  dev:
    commands:
      - name: "Lint"
        command: "ruff check ."
      - name: "Tests"
        command: "pytest"
    artifact: "DEVELOPMENT.md"
    pass_marker: "COMPLETED"
    fail_marker: "FAILED"
    required_artifacts:
      - "DEVELOPMENT.md"

  test:
    commands:
      - name: "Full test suite"
        command: "pytest --cov=src"
    rollback_to: "DEV"

  migration:
    skip_if:
      no_files_match: "**/migrations/**"
    commands:
      - name: "Apply migrations"
        command: "alembic upgrade head"
```

### ai

AI backend configuration:

```yaml
ai:
  default: "claude"
  backends:
    claude:
      command: "claude"
      args:
        - "--verbose"
      max_turns: 200
  stage_backends:
    REVIEW: codex
  profile: null
  profiles: {}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default` | string | `"claude"` | Default backend to use |
| `backends` | dict | - | Backend configurations |
| `backends.<name>.command` | string | - | CLI command |
| `backends.<name>.args` | list | `[]` | Additional arguments |
| `backends.<name>.max_turns` | int | `200` | Max AI turns |
| `backends.<name>.read_only` | bool | `false` | Backend runs in read-only mode; artifacts written via post-processing |
| `stage_backends` | dict | `{}` | Per-stage backend overrides (e.g., `{"REVIEW": "codex"}`) |
| `profile` | string | `null` | Active profile name (see [AI Profiles](#ai-profiles)) |
| `profiles` | dict | `{}` | Named routing profiles (see [AI Profiles](#ai-profiles)) |

### peer_review

Optional peer review hook that runs a second AI backend after configured stages:

```yaml
peer_review:
  enabled: true
  backend: "codex"
  stages: ["PM", "DESIGN"]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable peer review after configured stages |
| `backend` | string | `"codex"` | Which AI backend performs the review |
| `stages` | list | `["PM", "DESIGN"]` | Which stages get peer reviewed |

When enabled, after a configured stage completes successfully, a second AI backend independently reviews the output. If the reviewer disagrees, both opinions are shown to the user who makes the final call. If the reviewer backend is unavailable or fails, the workflow continues normally (graceful degradation).

### AI Profiles

Profiles let you define named AI routing strategies and switch between them with a single config change. This is useful when hitting API usage limits and needing to quickly reroute work to a different backend.

A profile bundles `default`, `stage_backends`, and optionally `peer_review_backend` into a named preset. When a profile is active, its values override the top-level `ai.default` and `ai.stage_backends` fields.

```yaml
ai:
  profile: default              # Change this one line to switch

  profiles:
    default:
      default: claude
      stage_backends:
        QA: codex
        REVIEW: codex

    no-claude:
      default: gemini
      stage_backends:
        QA: codex
        REVIEW: codex
      peer_review_backend: codex

    codex-primary:
      default: codex
      stage_backends:
        PM: gemini
        DESIGN: gemini
        QA: gemini
        REVIEW: gemini
      peer_review_backend: gemini

  backends:
    claude:
      command: "claude"
      args: ["--output-format", "stream-json", "--verbose"]
    codex:
      command: "codex"
      args: ["exec", "--full-auto"]
    gemini:
      command: "gemini-cli"
```

**Profile fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `default` | string | yes | Default backend when this profile is active |
| `stage_backends` | dict | no | Per-stage backend overrides |
| `peer_review_backend` | string | no | Override `peer_review.backend` when active |

**How resolution works:**

1. If `ai.profile` is not set, the top-level `ai.default` and `ai.stage_backends` are used as-is (fully backwards compatible).
2. If `ai.profile` names a profile, that profile's `default` and `stage_backends` replace the top-level values at config load time. All existing code that reads `config.ai.default` works unchanged.
3. If the profile has `peer_review_backend`, it also overrides `peer_review.backend`.
4. If `ai.profile` names a profile that doesn't exist, config validation fails with an error.

**CLI commands:**

```bash
# Show active profile and routing table
galangal profile

# List all defined profiles (* marks active)
galangal profile list

# Switch to a different profile
galangal profile switch no-claude
```

The `switch` command updates `ai.profile` in `.galangal/config.yaml`. The change takes effect on the next `galangal resume` or `galangal start`.

### docs

Documentation paths and update settings:

```yaml
docs:
  changelog_dir: "docs/changelog"
  security_audit: "docs/security"
  general: "docs"
  update_changelog: true
  update_security_audit: true
  update_general_docs: true
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `changelog_dir` | string | `"docs/changelog"` | Changelog location |
| `security_audit` | string | `"docs/security"` | Security docs location |
| `general` | string | `"docs"` | General docs location |
| `update_changelog` | bool | `true` | Update changelog in DOCS stage |
| `update_security_audit` | bool | `true` | Update security docs |
| `update_general_docs` | bool | `true` | Update general docs |

### tasks_dir

Task storage location:

```yaml
tasks_dir: "galangal-tasks"
```

Default: `"galangal-tasks"`

Tasks are stored in `<tasks_dir>/<task-name>/`.

### prompt_context

Global context added to all prompts:

```yaml
prompt_context: |
  This project uses:
  - FastAPI for backend APIs
  - React with TypeScript for frontend
  - PostgreSQL database
  - Redis for caching

  Follow existing code patterns and conventions.
```

### stage_context

Per-stage context added to specific prompts:

```yaml
stage_context:
  PM: |
    Focus on technical requirements.
    Include API specifications.

  DEV: |
    Use SQLAlchemy for database operations.
    All endpoints need input validation.
    Follow REST conventions.

  TEST: |
    Use pytest for all tests.
    Maintain 80% code coverage.
    Include integration tests.

  SECURITY: |
    Check for OWASP Top 10 vulnerabilities.
    Verify authentication and authorization.
```

### branch_pattern

Git branch naming pattern for new tasks:

```yaml
branch_pattern: "task/{task_name}"
```

Default: `"task/{task_name}"`

The `{task_name}` placeholder is replaced with the task slug.

### test_gate

Mechanical test verification stage that runs configured test suites without AI:

```yaml
test_gate:
  enabled: true
  tests:
    - name: "Unit tests"
      command: "pytest tests/unit"
      timeout: 300
    - name: "Integration tests"
      command: "pytest tests/integration"
      timeout: 600
  fail_fast: true
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable the test gate stage |
| `tests` | list | `[]` | Test suites to run |
| `tests[].name` | string | - | Display name for the test suite |
| `tests[].command` | string | - | Command to run |
| `tests[].timeout` | int | `300` | Timeout per test suite (seconds) |
| `fail_fast` | bool | `true` | Stop on first failure instead of running all |

### pr

Pull request configuration:

```yaml
pr:
  codex_review: false
  base_branch: "main"
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `codex_review` | bool | `false` | Add @codex review to PR body |
| `base_branch` | string | `"main"` | Base branch for PRs |

### logging

Structured logging configuration:

```yaml
logging:
  enabled: true
  level: "info"
  file: "logs/galangal.jsonl"
  activity_file: "galangal-tasks/{task_name}/activity.jsonl"
  json_format: true
  console: false
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable structured logging to file |
| `level` | string | `"info"` | Log level: debug, info, warning, error |
| `file` | string | `null` | Log file path. If not set, logs only to console |
| `activity_file` | string | `null` | Activity log path. Supports `{task_name}` placeholder |
| `json_format` | bool | `true` | Output JSON format (false for pretty console) |
| `console` | bool | `false` | Also output to console (stderr) |

### github

GitHub integration configuration:

```yaml
github:
  pickup_label: "galangal"
  in_progress_label: "in-progress"
  label_colors:
    galangal: "7C3AED"
    in-progress: "FCD34D"
  label_mapping:
    bug: ["bug", "bugfix"]
    feature: ["enhancement", "feature"]
    docs: ["documentation", "docs"]
    refactor: ["refactor"]
    chore: ["chore", "maintenance"]
    hotfix: ["hotfix", "critical"]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pickup_label` | string | `"galangal"` | Label that marks issues for galangal to pick up |
| `in_progress_label` | string | `"in-progress"` | Label added when galangal starts an issue |
| `label_colors` | dict | - | Hex colors for labels (without `#`) |
| `label_mapping` | object | - | Maps GitHub labels to task types |

### task_type_settings

Per-task-type settings:

```yaml
task_type_settings:
  bug_fix:
    skip_discovery: true
  hotfix:
    skip_discovery: true
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `<type>.skip_discovery` | bool | `false` | Skip the PM discovery Q&A phase for this task type |

### artifact_context

Per-stage artifact context filtering to control which artifacts are included in prompts. Reduces token usage by only including relevant context:

```yaml
artifact_context:
  dev:
    required: ["SPEC.md"]
    include: ["DESIGN.md", "PLAN.md"]
    exclude: ["DISCOVERY_LOG.md"]
  test:
    required: ["SPEC.md", "DEVELOPMENT.md"]
    include: ["TEST_PLAN.md"]
```

| Field | Type | Description |
|-------|------|-------------|
| `<stage>.required` | list | Artifacts that must be included (error if missing) |
| `<stage>.include` | list | Artifacts to include if they exist |
| `<stage>.exclude` | list | Artifacts to never include (overrides include) |

If a stage is not configured here, it falls back to default behavior.

### lineage

Artifact lineage tracking for staleness detection:

```yaml
lineage:
  enabled: true
  block_on_staleness: true
  artifact_dependencies:
    DESIGN.md:
      - artifact: "SPEC.md"
        sections: ["Requirements"]
  stage_dependencies:
    DEV:
      depends_on_stages: ["DESIGN"]
      depends_on_artifacts:
        - artifact: "SPEC.md"
        - artifact: "DESIGN.md"
          sections: ["Architecture"]
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable lineage tracking |
| `block_on_staleness` | bool | `true` | Force re-run of stale stages (vs just warning) |
| `artifact_dependencies` | dict | `{}` | Per-artifact dependency specs |
| `stage_dependencies` | dict | `{}` | Per-stage dependency configuration |

### hub

Hub connection for remote monitoring and control. See [Hub Documentation](../hub/README.md) for full setup.

```yaml
hub:
  enabled: true
  url: "ws://your-server:8080/ws/agent"
  api_key: "your-api-key"
```

## Example Configurations

### Minimal Configuration

```yaml
project:
  name: "My App"

stages:
  skip:
    - BENCHMARK
    - CONTRACT
```

### Full-Featured Configuration

```yaml
project:
  name: "Enterprise App"
  approver_name: "Tech Lead"

stages:
  skip: []
  timeout: 7200
  max_retries: 3

validation:
  preflight:
    checks:
      - name: "Python 3.12+"
        type: command
        command: "python --version"
        expect_output: "3.12"
      - name: "Node 20+"
        type: command
        command: "node --version"
        expect_output: "v20"
      - name: "Docker running"
        type: command
        command: "docker info"

  dev:
    commands:
      - name: "Backend lint"
        command: "cd backend && ruff check ."
      - name: "Frontend lint"
        command: "cd frontend && npm run lint"
      - name: "Type check"
        command: "cd backend && mypy src/"
      - name: "Unit tests"
        command: "cd backend && pytest tests/unit"
    artifact: "DEVELOPMENT.md"
    pass_marker: "Implementation Complete"

  test:
    commands:
      - name: "Backend tests"
        command: "cd backend && pytest --cov=src --cov-fail-under=80"
      - name: "Frontend tests"
        command: "cd frontend && npm test"
    rollback_to: "DEV"

  migration:
    skip_if:
      no_files_match: "backend/alembic/versions/*.py"
    commands:
      - name: "Apply migrations"
        command: "cd backend && alembic upgrade head"

  qa:
    commands:
      - name: "Integration tests"
        command: "cd backend && pytest tests/integration"
      - name: "E2E tests"
        command: "cd frontend && npm run test:e2e"
    rollback_to: "DEV"

  security:
    commands:
      - name: "Python security scan"
        command: "cd backend && bandit -r src/"
        optional: true
      - name: "NPM audit"
        command: "cd frontend && npm audit --audit-level=high"
        optional: true

ai:
  default: "claude"
  backends:
    claude:
      command: "claude"
      max_turns: 300

docs:
  changelog_dir: "docs/changelog"
  security_audit: "docs/security"
  general: "docs"
  update_changelog: true
  update_security_audit: true
  update_general_docs: true

tasks_dir: "galangal-tasks"

prompt_context: |
  Enterprise application with microservices architecture.

  Backend:
  - FastAPI with async endpoints
  - SQLAlchemy ORM with PostgreSQL
  - Redis caching layer
  - Celery for background tasks

  Frontend:
  - Next.js 14 with App Router
  - TailwindCSS for styling
  - React Query for data fetching

stage_context:
  DEV: |
    Follow existing patterns in the codebase.
    Add comprehensive error handling.
    Include logging for debugging.

  TEST: |
    Write tests for happy path and edge cases.
    Mock external services.
    Use fixtures for database state.

  SECURITY: |
    Check authentication on all endpoints.
    Verify CORS configuration.
    Review SQL query safety.
```

## Configuration Loading

Configuration is loaded and cached by `config/loader.py`:

```python
from galangal.config.loader import get_config

config = get_config()  # Cached globally
```

The loader:
1. Looks for `.galangal/config.yaml`
2. Falls back to defaults if not found
3. Validates via Pydantic models
4. Caches result for the session

## Initializing Configuration

Create initial config with:

```bash
galangal init
```

This creates:
- `.galangal/config.yaml` - Base configuration
- `.galangal/prompts/` - Prompt override directory

## Related Documentation

- [Architecture](../local-development/architecture.md) - System overview
- [Validation System](../local-development/validation-system.md) - Validation details
- [Prompt System](prompt-system.md) - Prompt configuration
- [Extending](extending.md) - Customization guide
