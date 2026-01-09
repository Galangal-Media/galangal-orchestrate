# Extending Galangal

This document describes how to extend and customize Galangal for your specific needs.

## Extension Points

Galangal provides several extension points:

1. **Custom Prompts** - Per-project prompt overrides
2. **Validation Rules** - Custom validation commands
3. **New Task Types** - Additional task categories
4. **New Stages** - Custom workflow stages (requires code changes)
5. **New AI Backends** - Support for other AI providers
6. **New CLI Commands** - Additional commands

## Custom Prompts

### Override a Stage Prompt

Create a file in `.galangal/prompts/<stage>.md`:

```markdown
# My Custom DEV Prompt

[Your custom instructions]

# BASE

[Additional instructions after base content]
```

The `# BASE` marker indicates where the default prompt content should be inserted.

### Full Replacement

Omit the `# BASE` marker to completely replace the default:

```markdown
# My Complete DEV Prompt

[All your custom instructions - no base content included]
```

### Example: Custom Security Prompt

`.galangal/prompts/security.md`:

```markdown
# Security Review for Our Stack

Our application uses:
- FastAPI with OAuth2
- PostgreSQL with SQLAlchemy
- Redis for sessions

# BASE

## Additional Security Checks

1. Verify all endpoints require authentication
2. Check for SQL injection in raw queries
3. Validate CORS configuration
4. Review session timeout settings
5. Check for sensitive data in logs
```

### Example: Custom QA Prompt

`.galangal/prompts/qa.md`:

```markdown
# QA Process

## Testing Requirements

- All tests must pass
- Code coverage must be at least 80%
- No console.log statements in production code
- All API responses must be typed

# BASE

## Our Specific Checks

1. Verify database migrations are reversible
2. Check API response times
3. Validate error messages are user-friendly
```

## Custom Validation Rules

### Add Validation Commands

In `.galangal/config.yaml`:

```yaml
validation:
  dev:
    commands:
      # Standard checks
      - name: "Lint"
        command: "ruff check ."

      # Custom project checks
      - name: "Check imports"
        command: "python scripts/check_imports.py"

      - name: "Verify configs"
        command: "./scripts/validate-configs.sh"

      # Optional checks (don't fail the stage)
      - name: "Coverage report"
        command: "pytest --cov=src --cov-report=html"
        optional: true
```

### Add Preflight Checks

```yaml
validation:
  preflight:
    checks:
      - name: "Docker running"
        type: command
        command: "docker info"

      - name: "Database accessible"
        type: command
        command: "pg_isready -h localhost"

      - name: "Redis available"
        type: command
        command: "redis-cli ping"
        expect_output: "PONG"

      - name: "Config file exists"
        type: path
        path: ".env"
```

### Add Skip Conditions

```yaml
validation:
  migration:
    skip_if:
      no_files_match: "alembic/versions/*.py"

  contract:
    skip_if:
      no_files_match: "openapi/*.yaml"
```

## Adding Task Types

### Modify Source Code

Edit `src/galangal/core/state.py`:

```python
class TaskType(Enum):
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    CHORE = "chore"
    DOCS = "docs"
    HOTFIX = "hotfix"
    # Add your new type
    SPIKE = "spike"
```

### Define Skip Stages

```python
TASK_TYPE_SKIP_STAGES = {
    # ... existing types ...
    TaskType.SPIKE: [
        Stage.DESIGN,
        Stage.MIGRATION,
        Stage.CONTRACT,
        Stage.BENCHMARK,
        Stage.SECURITY,
        Stage.DOCS,
    ],
}
```

### Update CLI

Edit `src/galangal/commands/start.py` to include the new type in help text and validation.

## Adding Workflow Stages

Adding a new stage requires several code changes:

### 1. Define the Stage

In `src/galangal/core/state.py`:

```python
class Stage(Enum):
    PM = "PM"
    DESIGN = "DESIGN"
    # Add new stage
    ARCHITECTURE = "ARCHITECTURE"
    PREFLIGHT = "PREFLIGHT"
    # ...
```

### 2. Update Stage Order

```python
STAGE_ORDER = [
    Stage.PM,
    Stage.DESIGN,
    Stage.ARCHITECTURE,  # New stage
    Stage.PREFLIGHT,
    # ...
]
```

### 3. Add Stage Metadata

```python
STAGE_METADATA = {
    # ...
    Stage.ARCHITECTURE: StageMetadata(
        display_name="Architecture",
        description="Define system architecture",
        artifact="ARCHITECTURE.md",
        requires=["SPEC.md", "PLAN.md", "DESIGN.md"],
        conditional=False,
    ),
    # ...
}
```

### 4. Create Default Prompt

Create `src/galangal/prompts/defaults/architecture.md`:

```markdown
# Architecture Stage

You are defining the system architecture for the task.

Based on the specification and design, create an architecture document.

## Required Output

Create ARCHITECTURE.md with:
- Component diagram
- Data flow
- Technology choices
- Scalability considerations
```

### 5. Add Validation Config Schema

Update `src/galangal/config/schema.py` if needed.

## Adding AI Backends

### Create Backend Class

Create `src/galangal/ai/mybackend.py`:

```python
from galangal.ai.base import AIBackend
from galangal.results import StageResult

class MyBackend(AIBackend):
    def __init__(self, config: dict):
        self.config = config

    def invoke(
        self,
        prompt: str,
        timeout: int = 14400,
        max_turns: int = 200,
        ui = None,
        pause_check = None,
    ) -> StageResult:
        # Implement AI invocation
        pass
```

### Register Backend

Update `src/galangal/ai/__init__.py`:

```python
from galangal.ai.mybackend import MyBackend

BACKENDS = {
    "claude": ClaudeBackend,
    "mybackend": MyBackend,
}
```

### Configure Backend

```yaml
ai:
  default: "mybackend"
  backends:
    mybackend:
      api_key: "..."
      model: "..."
```

## Adding CLI Commands

### Create Command Module

Create `src/galangal/commands/mycommand.py`:

```python
def run(args) -> int:
    """Execute the mycommand command."""
    # Implementation
    return 0
```

### Register Command

Update `src/galangal/cli.py`:

```python
def _cmd_mycommand(args) -> int:
    from galangal.commands.mycommand import run
    return run(args)

# Add to argument parser
subparsers.add_parser(
    "mycommand",
    help="Description of my command"
)
```

## Project-Specific Scripts

### Validation Scripts

Create scripts for custom validation:

`scripts/validate-api-contracts.py`:

```python
#!/usr/bin/env python
import sys
import json

def validate_contracts():
    # Load and validate OpenAPI specs
    # Return 0 for success, 1 for failure
    pass

if __name__ == "__main__":
    sys.exit(validate_contracts())
```

Use in config:

```yaml
validation:
  contract:
    commands:
      - name: "Validate API contracts"
        command: "python scripts/validate-api-contracts.py"
```

### Pre-Stage Hooks

Create hooks that run before stages:

`scripts/pre-dev.sh`:

```bash
#!/bin/bash
# Ensure dependencies are up to date
pip install -r requirements.txt
npm install
```

Reference in prompt context:

```yaml
stage_context:
  DEV: |
    Before starting development, run: ./scripts/pre-dev.sh
```

## Testing Extensions

### Test Custom Prompts

```bash
# View assembled prompt
galangal prompts show dev

# Export for review
galangal prompts export ./test-prompts/
```

### Test Validation Rules

```bash
# Run validation commands manually
ruff check .
pytest
python scripts/validate-api-contracts.py
```

### Test in Sandbox

```bash
mkdir sandbox
cd sandbox
galangal init
galangal start "Test extension" --type feature
galangal resume
```

## Best Practices

### 1. Start with Prompts

Customize prompts before adding validation rules. Often prompt changes are sufficient.

### 2. Use Optional Validations

Mark experimental validations as optional:

```yaml
commands:
  - name: "Experimental check"
    command: "./scripts/experimental.sh"
    optional: true
```

### 3. Document Custom Extensions

Add comments to your config:

```yaml
validation:
  dev:
    commands:
      # Required by our CI pipeline
      - name: "Format check"
        command: "black --check ."

      # Internal quality metric
      - name: "Complexity check"
        command: "radon cc src/ -a"
        optional: true
```

### 4. Version Control Extensions

Include `.galangal/` in version control so team members share the same configuration.

### 5. Test Incrementally

Add one extension at a time and test thoroughly before adding more.

## Related Documentation

- [Architecture](architecture.md) - System overview
- [Configuration](configuration.md) - Config options
- [Prompt System](prompt-system.md) - Prompt customization
- [Validation System](validation-system.md) - Validation rules
