# Validation System

This document describes how Galangal validates stage outputs using the `ValidationRunner`.

## Overview

The `ValidationRunner` class (`validation/runner.py`) executes config-driven validation after each stage completes. Validation determines whether to:

- Proceed to the next stage
- Retry the current stage
- Roll back to an earlier stage

## ValidationResult Model

```python
@dataclass
class ValidationResult:
    success: bool           # Pass or fail
    message: str            # Human-readable result
    rollback_to: Stage | None  # Target stage for rollback
    skipped: bool           # True if stage was skipped
```

## Validation Types

### 1. Skip Conditions

Check if a stage should be skipped entirely:

```yaml
validation:
  migration:
    skip_if:
      no_files_match: "**/*migration*"
```

The stage is skipped if the glob pattern matches no files in the git diff.

### 2. Preflight Checks

Special validation for PREFLIGHT stage:

```yaml
validation:
  preflight:
    checks:
      - name: "Python installed"
        type: path
        path: "/usr/bin/python3"

      - name: "Node available"
        type: command
        command: "node --version"
        expect_output: "v"
```

Check types:
- `path`: Verify file/directory exists
- `command`: Run command, optionally validate output

### 3. Validation Commands

Shell commands that must succeed:

```yaml
validation:
  dev:
    commands:
      - name: "Lint"
        command: "ruff check ."

      - name: "Type check"
        command: "mypy src/"
        optional: true

      - name: "Build"
        command: "npm run build"
        allow_failure: false
```

Options:
- `optional: true` - Failure doesn't fail the stage
- `allow_failure: true` - Log failure but continue

### 4. Artifact Markers

Check for specific markers in artifacts:

```yaml
validation:
  dev:
    artifact: "DEVELOPMENT.md"
    pass_marker: "COMPLETED"
    fail_marker: "FAILED"
```

The `ValidationRunner` searches the artifact for these markers to determine success.

### 5. Required Artifacts

Verify expected files exist:

```yaml
validation:
  pm:
    required_artifacts:
      - "SPEC.md"
      - "PLAN.md"
```

## Configuration Structure

Full validation config structure:

```yaml
validation:
  preflight:
    checks:
      - name: "Check name"
        type: "path" | "command"
        path: "/path/to/check"
        command: "command to run"
        expect_output: "expected substring"

  <stage_name>:
    skip_if:
      no_files_match: "glob/pattern/**"

    commands:
      - name: "Command name"
        command: "shell command"
        optional: false
        allow_failure: false

    artifact: "ARTIFACT_NAME.md"
    pass_marker: "PASS_STRING"
    fail_marker: "FAIL_STRING"

    required_artifacts:
      - "FILE1.md"
      - "FILE2.md"

    rollback_to: "DEV"
```

## Validation Flow

```
Stage Completes
     ↓
Check skip_if conditions
     ↓ (not skipped)
Run preflight checks (if PREFLIGHT)
     ↓
Run validation commands
     ↓
Check artifact markers
     ↓
Verify required artifacts
     ↓
Return ValidationResult
```

## Example Configurations

### Development Stage

```yaml
validation:
  dev:
    commands:
      - name: "Lint check"
        command: "ruff check src/"

      - name: "Type check"
        command: "mypy src/"
        optional: true

      - name: "Unit tests"
        command: "pytest tests/unit -v"

    artifact: "DEVELOPMENT.md"
    pass_marker: "## Implementation Complete"

    required_artifacts:
      - "DEVELOPMENT.md"
```

### Test Stage

```yaml
validation:
  test:
    commands:
      - name: "Run all tests"
        command: "pytest --cov=src --cov-report=term"

      - name: "Coverage check"
        command: "pytest --cov=src --cov-fail-under=80"
        optional: true

    artifact: "TEST_PLAN.md"
    pass_marker: "All tests passing"
    fail_marker: "Tests failed"

    rollback_to: "DEV"
```

### QA Stage

```yaml
validation:
  qa:
    commands:
      - name: "Integration tests"
        command: "pytest tests/integration -v"

      - name: "E2E tests"
        command: "npm run test:e2e"
        optional: true

    artifact: "QA_REPORT.md"
    pass_marker: "QA APPROVED"
    fail_marker: "QA REJECTED"

    rollback_to: "DEV"
```

### Migration Stage (Conditional)

```yaml
validation:
  migration:
    skip_if:
      no_files_match: "**/migrations/**"

    commands:
      - name: "Run migrations"
        command: "alembic upgrade head"

      - name: "Verify schema"
        command: "python scripts/verify_schema.py"

    artifact: "MIGRATION_REPORT.md"
    pass_marker: "Migrations applied"
```

### Security Stage

```yaml
validation:
  security:
    commands:
      - name: "Security scan"
        command: "npm audit --audit-level=high"
        allow_failure: true

      - name: "SAST scan"
        command: "bandit -r src/"
        optional: true

    artifact: "SECURITY_CHECKLIST.md"
    pass_marker: "SECURITY APPROVED"
    fail_marker: "SECURITY REJECTED"
```

## Rollback Triggers

Validation can trigger rollback:

### Explicit Rollback Configuration

```yaml
validation:
  qa:
    rollback_to: "DEV"
```

If QA validation fails, workflow rolls back to DEV stage.

### Implicit Rollback

Some validations imply rollback:
- Test failures → Roll back to DEV
- QA rejection → Roll back to DEV

## Skip Artifacts

Manual skip via artifact files:

```
MIGRATION_SKIP.md
CONTRACT_SKIP.md
BENCHMARK_SKIP.md
```

Content doesn't matter; presence of file triggers skip.

## ValidationRunner API

```python
from galangal.validation.runner import ValidationRunner

runner = ValidationRunner(config)
result = runner.validate_stage(
    stage=Stage.DEV,
    task_dir=Path("galangal-tasks/my-task"),
)

if result.success:
    # Proceed to next stage
elif result.rollback_to:
    # Roll back to specified stage
else:
    # Retry current stage
```

## Debugging Validation

### View Validation Config

```bash
cat .galangal/config.yaml
```

### Run Commands Manually

Test validation commands outside the workflow:

```bash
cd /path/to/project
ruff check src/
pytest tests/ -v
```

### Check Artifact Markers

```bash
grep "COMPLETED" galangal-tasks/my-task/DEVELOPMENT.md
```

### View Validation Logs

Stage logs include validation output:

```bash
cat galangal-tasks/my-task/logs/dev_1.log
```

## Best Practices

### 1. Start Simple

Begin with basic validation and add complexity as needed:

```yaml
validation:
  dev:
    commands:
      - name: "Tests pass"
        command: "pytest"
```

### 2. Use Optional for Non-Critical

Mark non-blocking checks as optional:

```yaml
commands:
  - name: "Coverage report"
    command: "pytest --cov=src"
    optional: true
```

### 3. Clear Artifact Markers

Use distinctive markers:

```yaml
pass_marker: "## IMPLEMENTATION COMPLETE"
fail_marker: "## IMPLEMENTATION FAILED"
```

### 4. Specific Glob Patterns

For skip conditions, be specific:

```yaml
skip_if:
  no_files_match: "src/db/migrations/*.py"
```

### 5. Document Rollback Behavior

When using `rollback_to`, document expectations:

```yaml
# QA failures roll back to DEV for fixes
qa:
  rollback_to: "DEV"
```

## Related Documentation

- [Architecture](architecture.md) - System overview
- [Workflow Pipeline](workflow-pipeline.md) - Stage execution
- [Configuration](configuration.md) - Full config reference
