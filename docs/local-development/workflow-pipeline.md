# Workflow Pipeline

This document describes the 13-stage workflow pipeline, how stages execute, and how rollback works.

## Stage Overview

The workflow follows a deterministic 13-stage pipeline:

```
PM → DESIGN → PREFLIGHT → DEV → MIGRATION → TEST →
CONTRACT → QA → BENCHMARK → SECURITY → REVIEW → DOCS → COMPLETE
```

Each stage has a specific purpose and produces artifacts that inform subsequent stages.

## Stage Descriptions

| Stage | Purpose | Artifact |
|-------|---------|----------|
| **PM** | Requirements gathering and specification | `SPEC.md`, `PLAN.md` |
| **DESIGN** | System design and architecture | `DESIGN.md` |
| **PREFLIGHT** | Environment validation | `PREFLIGHT_REPORT.md` |
| **DEV** | Implementation | `DEVELOPMENT.md` |
| **MIGRATION** | Database/schema migrations | `MIGRATION_REPORT.md` |
| **TEST** | Test writing and execution | `TEST_PLAN.md` |
| **CONTRACT** | API contract validation | `CONTRACT_REPORT.md` |
| **QA** | Quality assurance | `QA_REPORT.md` |
| **BENCHMARK** | Performance testing | `BENCHMARK_REPORT.md` |
| **SECURITY** | Security review | `SECURITY_CHECKLIST.md` |
| **REVIEW** | Code review | `REVIEW_NOTES.md` |
| **DOCS** | Documentation updates | `DOCS_REPORT.md` |
| **COMPLETE** | Workflow completion | - |

## Stage Execution Flow

### 1. Stage Entry

When entering a stage, the system:

1. Checks if the stage should be skipped
2. Resets attempt counter if coming from a different stage
3. Logs stage entry

### 2. Prompt Building

The `PromptBuilder` assembles the full prompt:

```python
prompt = PromptBuilder.build(
    stage=Stage.DEV,
    state=workflow_state,
    config=config,
)
```

The prompt includes:
- Base stage prompt (from `prompts/defaults/`)
- Project overrides (from `.galangal/prompts/`)
- Task context (name, type, description)
- Relevant artifacts (stage-specific, see below)
- Failure context (if retry)

#### Artifact Context by Stage

Artifacts are included based on what each stage actually needs:

| Stage | Artifacts Included |
|-------|-------------------|
| **PM** | `DISCOVERY_LOG.md` (user Q&A) |
| **DESIGN** | `SPEC.md` |
| **PREFLIGHT+** | `SPEC.md`, `DESIGN.md` or `PLAN.md`* |
| **DEV** | + `DEVELOPMENT.md` (resume), `ROLLBACK.md` (issues) |
| **TEST** | + `TEST_PLAN.md`, `ROLLBACK.md` |
| **CONTRACT** | + `TEST_PLAN.md` |
| **REVIEW** | + `QA_REPORT.md`, `SECURITY_CHECKLIST.md` |

*If DESIGN stage ran, `DESIGN.md` is used. If skipped, `PLAN.md` is included instead.

Key design decisions:
- **DESIGN.md supersedes PLAN.md** — when DESIGN runs, its output replaces PLAN as the implementation guide
- **PLAN.md used when DESIGN skipped** — task types like bug_fix, refactor, chore skip DESIGN, so PLAN.md remains the implementation guide
- **DISCOVERY_LOG.md is only for PM** — its content is captured in `SPEC.md`
- **Previous reports not included in DEV/TEST** — `ROLLBACK.md` summarizes what needs fixing

### 3. AI Invocation

The `ClaudeBackend` invokes the Claude CLI:

```bash
cat '<prompt_file>' | claude \
  --output-format stream-json \
  --verbose \
  --max-turns 200 \
  --permission-mode acceptEdits
```

The backend:
- Streams JSON output for real-time updates
- Monitors for tool use events
- Supports graceful pause via callback
- Returns structured `StageResult`

### 4. Validation

After AI completion, `ValidationRunner` validates:

1. **Skip conditions**: Check if stage should be skipped
2. **Required artifacts**: Verify expected files exist
3. **Artifact markers**: Check for PASS/FAIL markers
4. **Custom commands**: Run configured shell commands

### 5. Result Handling

Based on validation:

- **Success**: Move to next stage
- **Validation Failed**: Retry or rollback
- **Rollback Required**: Jump to earlier stage

## Stage Skipping

Stages can be skipped based on several conditions:

### 1. Config-Level Skipping

In `.galangal/config.yaml`:

```yaml
stages:
  skip:
    - SECURITY
    - BENCHMARK
```

### 2. Task Type Skipping

Different task types skip different stages:

| Task Type | Skipped Stages |
|-----------|----------------|
| **feature** | None |
| **bug_fix** | DESIGN, BENCHMARK |
| **refactor** | DESIGN, MIGRATION, CONTRACT, BENCHMARK, SECURITY |
| **chore** | DESIGN, MIGRATION, CONTRACT, BENCHMARK |
| **docs** | DESIGN, PREFLIGHT, MIGRATION, TEST, CONTRACT, QA, BENCHMARK, SECURITY |
| **hotfix** | DESIGN, BENCHMARK |

### 3. Skip Artifacts

Manual skip via artifact file:

```
MIGRATION_SKIP.md
CONTRACT_SKIP.md
BENCHMARK_SKIP.md
```

### 4. Conditional Skip

Based on git diff patterns:

```yaml
validation:
  migration:
    skip_if:
      no_files_match: "**/*migration*"
```

## PM Discovery Flow

The PM stage has a special discovery sub-flow:

1. **Question Generation**: Claude generates clarifying questions
2. **User Answers**: User provides answers via TUI modal
3. **Answer Storage**: Answers saved to `DISCOVERY_LOG.md`
4. **Spec Generation**: PM uses answers as authoritative requirements

This happens before the main PM prompt execution.

## Rollback Mechanism

### Triggering Rollback

Rollback occurs when:
- Validation explicitly returns `rollback_to` target
- Stage fails and config specifies rollback behavior
- QA finds issues requiring DEV fixes

### Rollback Flow

```
1. Current stage fails validation
2. ValidationResult contains rollback_to target
3. Issues appended to ROLLBACK.md
4. State moves to target stage
5. Target stage prompt includes ROLLBACK.md context
```

### Rollback Context

When rolling back, the `ROLLBACK.md` file captures:

```markdown
## Rollback from QA to DEV
**Timestamp**: 2024-01-15 10:30:00
**Reason**: Test failures detected

### Issues to Fix
- Authentication middleware not handling edge case
- Missing validation on user input
```

### Loop Prevention

To prevent infinite rollback loops:

1. Track rollback events with timestamps
2. Count recent rollbacks to same stage (1-hour window)
3. Limit: max 3 rollbacks per stage per hour
4. If exceeded: Block rollback, require manual intervention

```python
@dataclass
class RollbackEvent:
    timestamp: datetime
    from_stage: Stage
    to_stage: Stage
    reason: str
```

### Resolved Rollbacks

After issues are fixed, rollback entries move to `ROLLBACK_RESOLVED.md`:

```markdown
## Resolved: Rollback from QA to DEV
**Resolved at**: 2024-01-15 11:45:00
**Original reason**: Test failures detected
**Resolution**: Fixed authentication and validation
```

## Retry Logic

### Attempt Tracking

Each stage tracks attempts:

```python
state.attempt = 1  # Incremented on each retry
```

### Retry with Context

On retry, the prompt includes failure context:

```markdown
## RETRY ATTEMPT 2

Previous attempt failed with:
[error message truncated to 4000 chars]

Please fix the issues and try again.
```

### Max Retries

Configurable in `.galangal/config.yaml`:

```yaml
stages:
  max_retries: 5
```

After max retries, workflow pauses for manual intervention.

## Stage Timeouts

Each stage has a timeout (default 4 hours):

```yaml
stages:
  timeout: 14400  # seconds
```

Timeout behavior:
- Claude process terminated
- Stage marked as failed
- Retry initiated (if within max_retries)

## Approval Gates

Certain stages require explicit approval:

- **DESIGN**: `galangal approve-design`
- **SPEC**: Implicit via PM completion

The workflow pauses at these gates until approval is granted.

## Logging

Each stage execution is logged:

```
galangal-tasks/<task-name>/logs/
├── pm_1.log
├── pm_2.log      # Retry
├── design_1.log
├── dev_1.log
├── dev_2.log     # After rollback
└── ...
```

Logs include:
- Full prompt sent
- Claude's complete output
- Tool use events
- Final result

## Related Documentation

- [Architecture](architecture.md) - System overview
- [State Management](state-management.md) - State persistence
- [Validation System](validation-system.md) - Validation details
- [Prompt System](prompt-system.md) - Prompt building
