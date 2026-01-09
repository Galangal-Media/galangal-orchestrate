# Prompt System

This document describes how Galangal builds prompts for each workflow stage, including base prompts, project overrides, and context injection.

## Overview

The `PromptBuilder` class (`prompts/builder.py`) assembles full prompts by merging:

1. **Base prompts** - Default stage instructions
2. **Project overrides** - Project-specific customizations
3. **Task context** - Current task information
4. **Artifact context** - Previous stage outputs
5. **Config context** - Additional instructions from config

## Base Prompts

Default stage prompts are located in:

```
src/galangal/prompts/defaults/
├── pm.md              # PM stage prompt
├── pm_questions.md    # PM discovery questions
├── design.md          # Design stage prompt
├── preflight.md       # Preflight stage prompt
├── dev.md             # Development stage prompt
├── migration.md       # Migration stage prompt
├── test.md            # Test stage prompt
├── contract.md        # Contract stage prompt
├── qa.md              # QA stage prompt
├── benchmark.md       # Benchmark stage prompt
├── security.md        # Security stage prompt
├── review.md          # Review stage prompt
└── docs.md            # Documentation stage prompt
```

These prompts are generic and designed to work across different projects.

## Project Overrides

Projects can customize prompts in:

```
.galangal/prompts/
├── pm.md
├── dev.md
└── ...
```

### Override Modes

**1. Supplement Mode (with `# BASE` marker)**

Include the `# BASE` marker where the default prompt should be inserted:

```markdown
# Project-Specific Instructions

[Your custom instructions here]

# BASE

[Additional instructions after base content]
```

The base prompt content replaces the `# BASE` marker.

**2. Full Override Mode (no marker)**

Without a `# BASE` marker, the project prompt completely replaces the default:

```markdown
# Custom PM Stage

[Your complete custom prompt]
```

## Context Injection

### Task Context

Every prompt includes task information:

```markdown
## Task Information

**Task Name**: add-user-auth
**Task Type**: feature
**Description**: Add user authentication with JWT tokens
**Stage**: DEV
**Attempt**: 2
```

### Artifact Context

Prompts include relevant artifacts from previous stages:

| Stage | Included Artifacts |
|-------|-------------------|
| DESIGN | SPEC.md, PLAN.md |
| DEV | SPEC.md, PLAN.md, DESIGN.md, ROLLBACK.md |
| TEST | SPEC.md, PLAN.md, DESIGN.md, DEVELOPMENT.md |
| QA | All above + TEST_PLAN.md |
| ... | Stage-appropriate artifacts |

Example artifact inclusion:

```markdown
## Specification (SPEC.md)

[Contents of SPEC.md]

## Implementation Plan (PLAN.md)

[Contents of PLAN.md]
```

### Failure Context

On retry attempts, failure context is included:

```markdown
## RETRY ATTEMPT 2

Previous attempt failed with:

[Error message from previous attempt, truncated to 4000 chars]

Please fix the issues and try again.
```

### Config Context

Additional context from configuration:

**Global context** (`prompt_context`):

```yaml
prompt_context: |
  This project uses FastAPI for the backend and React for the frontend.
  Follow the existing code patterns.
```

**Stage-specific context** (`stage_context`):

```yaml
stage_context:
  DEV: |
    Use SQLAlchemy for database operations.
    All new endpoints require tests.
  TEST: |
    Use pytest for all tests.
    Maintain 80% coverage minimum.
```

## PromptBuilder API

### Building a Prompt

```python
from galangal.prompts.builder import PromptBuilder

prompt = PromptBuilder.build(
    stage=Stage.DEV,
    state=workflow_state,
    config=config,
)
```

### Build Process

1. Load base prompt from `prompts/defaults/<stage>.md`
2. Check for project override in `.galangal/prompts/<stage>.md`
3. If override has `# BASE` marker, merge; otherwise replace
4. Inject task context
5. Inject relevant artifacts
6. Inject failure context (if retry)
7. Inject config context
8. Return assembled prompt

## Prompt Structure

A typical assembled prompt:

```markdown
# Development Stage

[Base/override prompt content]

---

## Context

### Task Information
- **Task**: add-user-auth
- **Type**: feature
- **Stage**: DEV (Attempt 2)

### Project Context
[prompt_context from config]

### Stage Context
[stage_context.DEV from config]

---

## Previous Artifacts

### SPEC.md
[Specification content]

### PLAN.md
[Plan content]

### DESIGN.md
[Design content]

### ROLLBACK.md
[Issues to fix]

---

## Previous Failure

RETRY ATTEMPT 2

[Error details]

---

## Instructions

[Stage-specific instructions]
```

## PM Discovery Prompts

The PM stage has a special discovery sub-flow:

### pm_questions.md

Used to generate clarifying questions:

```markdown
You are gathering requirements for a development task.

Based on the task description, generate 3-5 clarifying questions
that will help define the requirements precisely.

Task: {task_description}
```

### Discovery Log Integration

After Q&A, answers are stored in `DISCOVERY_LOG.md` and included in the main PM prompt:

```markdown
## Discovery Q&A

### Round 1

**Q1**: What authentication method should we use?
**A1**: JWT tokens with refresh token rotation.

**Q2**: Should we support social login?
**A2**: Not in the initial implementation.
```

## Documentation Path Injection

For DOCS and SECURITY stages, documentation paths are injected:

```yaml
docs:
  changelog_dir: "docs/changelog"
  security_audit: "docs/security"
  general: "docs"
```

Included in prompts as:

```markdown
## Documentation Paths

- Changelog: docs/changelog
- Security Audit: docs/security
- General Docs: docs
```

## Customization Examples

### Adding Project Standards

`.galangal/prompts/dev.md`:

```markdown
# Development Guidelines

- All code must pass ruff linting
- Use type hints on all functions
- Follow existing patterns in the codebase

# BASE

## Additional Requirements

- Update DEVELOPMENT.md with implementation notes
- Run tests before marking complete
```

### Custom QA Process

`.galangal/prompts/qa.md`:

```markdown
# QA Process

1. Run full test suite
2. Check for security vulnerabilities
3. Verify performance metrics
4. Review error handling

# BASE

## Project-Specific Checks

- Verify API response times < 200ms
- Check database query optimization
- Validate input sanitization
```

### Minimal Override

For a completely custom stage:

`.galangal/prompts/security.md`:

```markdown
# Security Review

Run our custom security scanning tool and document findings.

Command: npm run security:scan

Document all HIGH and CRITICAL findings in SECURITY_CHECKLIST.md.
```

## Debugging Prompts

To see the assembled prompt:

```bash
galangal prompts show dev
```

To export all prompts:

```bash
galangal prompts export ./exported-prompts/
```

## Related Documentation

- [Architecture](architecture.md) - System overview
- [Workflow Pipeline](workflow-pipeline.md) - Stage execution
- [Configuration](configuration.md) - Config options
