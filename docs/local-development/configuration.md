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
  stacks:
    - language: "python"
      framework: "fastapi"
      root: "backend/"
    - language: "typescript"
      framework: "vite"
      root: "frontend/"
  approver_name: "Optional Approver Name"

# Stage configuration
stages:
  skip: []              # Stages to always skip
  timeout: 14400        # Stage timeout in seconds (default: 4 hours)
  max_retries: 5        # Max retry attempts per stage

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

# Documentation paths
docs:
  changelog_dir: "docs/changelog"
  security_audit: "docs/security"
  general: "docs"
  update_changelog: true
  update_security_audit: true
  update_general_docs: true

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
```

## Configuration Sections

### project

Project metadata and stack information:

```yaml
project:
  name: "My Project"
  stacks:
    - language: "python"
      framework: "fastapi"
      root: "backend/"
    - language: "typescript"
      framework: "react"
      root: "frontend/"
  approver_name: "Lead Developer"
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Project display name |
| `stacks` | list | Technology stacks in the project |
| `stacks[].language` | string | Programming language |
| `stacks[].framework` | string | Framework used |
| `stacks[].root` | string | Root directory for this stack |
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

Valid stages to skip:
- `DESIGN`, `PREFLIGHT`, `MIGRATION`, `TEST`
- `CONTRACT`, `QA`, `BENCHMARK`
- `SECURITY`, `REVIEW`, `DOCS`

Note: `PM`, `DEV`, and `COMPLETE` cannot be skipped.

### validation

Per-stage validation rules. See [Validation System](validation-system.md) for details.

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
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default` | string | `"claude"` | Default backend to use |
| `backends` | dict | - | Backend configurations |
| `backends.<name>.command` | string | - | CLI command |
| `backends.<name>.args` | list | `[]` | Additional arguments |
| `backends.<name>.max_turns` | int | `200` | Max AI turns |

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

## Example Configurations

### Minimal Configuration

```yaml
project:
  name: "My App"
  stacks:
    - language: "python"
      framework: "fastapi"
      root: "."

stages:
  skip:
    - BENCHMARK
    - CONTRACT
```

### Full-Featured Configuration

```yaml
project:
  name: "Enterprise App"
  stacks:
    - language: "python"
      framework: "fastapi"
      root: "backend/"
    - language: "typescript"
      framework: "nextjs"
      root: "frontend/"
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

- [Architecture](architecture.md) - System overview
- [Validation System](validation-system.md) - Validation details
- [Prompt System](prompt-system.md) - Prompt configuration
- [Extending](extending.md) - Customization guide
