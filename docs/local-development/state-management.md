# State Management

This document describes how Galangal manages workflow state, including persistence, task types, and the state data model.

## State Location

State is persisted to JSON files in the task directory:

```
galangal-tasks/<task-name>/state.json
```

The active task is tracked in:

```
.galangal/active_task
```

## WorkflowState Model

The `WorkflowState` dataclass (`core/state.py`) contains:

```python
@dataclass
class WorkflowState:
    task_name: str
    task_description: str
    task_type: TaskType
    stage: Stage
    attempt: int
    started_at: datetime
    awaiting_approval: bool
    clarification_required: bool
    last_failure: str | None
    rollback_history: list[RollbackEvent]
    pm_subphase: str | None
    qa_rounds: list[dict] | None
    qa_complete: bool
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `task_name` | str | Unique task identifier (slug) |
| `task_description` | str | User-provided task description |
| `task_type` | TaskType | Type of task (feature, bug_fix, etc.) |
| `stage` | Stage | Current workflow stage |
| `attempt` | int | Current attempt number for stage |
| `started_at` | datetime | Task creation timestamp |
| `awaiting_approval` | bool | Waiting for user approval |
| `clarification_required` | bool | Waiting for user clarification |
| `last_failure` | str | Error message from previous attempt |
| `rollback_history` | list | History of rollback events |
| `pm_subphase` | str | PM discovery phase tracker |
| `qa_rounds` | list | QA iteration history |
| `qa_complete` | bool | QA process completed |

## Stage Enum

The `Stage` enum defines all workflow stages:

```python
class Stage(Enum):
    PM = "PM"
    DESIGN = "DESIGN"
    PREFLIGHT = "PREFLIGHT"
    DEV = "DEV"
    MIGRATION = "MIGRATION"
    TEST = "TEST"
    CONTRACT = "CONTRACT"
    QA = "QA"
    BENCHMARK = "BENCHMARK"
    SECURITY = "SECURITY"
    REVIEW = "REVIEW"
    DOCS = "DOCS"
    COMPLETE = "COMPLETE"
```

### Stage Metadata

Each stage has associated metadata:

```python
@dataclass
class StageMetadata:
    display_name: str      # Human-readable name
    description: str       # Stage purpose
    artifact: str | None   # Expected output file
    requires: list[str]    # Required input artifacts
    conditional: bool      # Can be skipped
```

The `STAGE_METADATA` dict maps stages to their metadata.

## TaskType Enum

The `TaskType` enum defines task categories:

```python
class TaskType(Enum):
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    CHORE = "chore"
    DOCS = "docs"
    HOTFIX = "hotfix"
```

### Task Type Stage Skipping

The `TASK_TYPE_SKIP_STAGES` dict defines which stages each task type skips:

```python
TASK_TYPE_SKIP_STAGES = {
    TaskType.FEATURE: [],
    TaskType.BUG_FIX: [Stage.DESIGN, Stage.BENCHMARK],
    TaskType.REFACTOR: [Stage.DESIGN, Stage.MIGRATION, Stage.CONTRACT, Stage.BENCHMARK, Stage.SECURITY],
    TaskType.CHORE: [Stage.DESIGN, Stage.MIGRATION, Stage.CONTRACT, Stage.BENCHMARK],
    TaskType.DOCS: [Stage.DESIGN, Stage.PREFLIGHT, Stage.MIGRATION, Stage.TEST, Stage.CONTRACT, Stage.QA, Stage.BENCHMARK, Stage.SECURITY],
    TaskType.HOTFIX: [Stage.DESIGN, Stage.BENCHMARK],
}
```

## RollbackEvent Model

Rollback events are tracked to prevent loops:

```python
@dataclass
class RollbackEvent:
    timestamp: datetime
    from_stage: Stage
    to_stage: Stage
    reason: str
```

## State Persistence

### Saving State

State is saved after every stage completion:

```python
def save_state(state: WorkflowState, task_dir: Path) -> None:
    state_file = task_dir / "state.json"
    state_file.write_text(json.dumps(asdict(state), default=str))
```

### Loading State

State is loaded at workflow start:

```python
def load_state(task_dir: Path) -> WorkflowState:
    state_file = task_dir / "state.json"
    data = json.loads(state_file.read_text())
    return WorkflowState(**data)
```

## State File Example

```json
{
  "task_name": "add-user-auth",
  "task_description": "Add user authentication with JWT tokens",
  "task_type": "feature",
  "stage": "DEV",
  "attempt": 2,
  "started_at": "2024-01-15T09:00:00",
  "awaiting_approval": false,
  "clarification_required": false,
  "last_failure": "Tests failed: missing validation on email field",
  "rollback_history": [
    {
      "timestamp": "2024-01-15T11:30:00",
      "from_stage": "QA",
      "to_stage": "DEV",
      "reason": "Test failures detected"
    }
  ],
  "pm_subphase": null,
  "qa_rounds": null,
  "qa_complete": false
}
```

## Active Task Tracking

The active task is tracked in `.galangal/active_task`:

```
add-user-auth
```

This allows commands like `galangal status` to know which task to display.

### Switching Tasks

Use `galangal switch <task-name>` to change active task:

```bash
galangal switch add-user-auth
```

## Task Directory Structure

Each task has its own directory:

```
galangal-tasks/add-user-auth/
├── state.json           # WorkflowState
├── SPEC.md              # PM output
├── PLAN.md              # PM output
├── DISCOVERY_LOG.md     # PM Q&A
├── DESIGN.md            # Design output
├── DEVELOPMENT.md       # Dev progress
├── ROLLBACK.md          # Issues to fix
├── ROLLBACK_RESOLVED.md # Fixed issues
├── TEST_PLAN.md         # Test output
├── QA_REPORT.md         # QA output
├── SECURITY_CHECKLIST.md
├── REVIEW_NOTES.md
├── DOCS_REPORT.md
└── logs/
    ├── pm_1.log
    ├── design_1.log
    ├── dev_1.log
    ├── dev_2.log
    └── ...
```

## State Transitions

### Normal Flow

```
State: {stage: PM, attempt: 1}
  ↓ PM completes
State: {stage: DESIGN, attempt: 1}
  ↓ DESIGN completes
State: {stage: PREFLIGHT, attempt: 1}
  ↓ ... continues through stages
State: {stage: COMPLETE, attempt: 1}
```

### Retry Flow

```
State: {stage: DEV, attempt: 1}
  ↓ Validation fails
State: {stage: DEV, attempt: 2, last_failure: "..."}
  ↓ Validation passes
State: {stage: TEST, attempt: 1}
```

### Rollback Flow

```
State: {stage: QA, attempt: 1}
  ↓ QA finds issues, rollback to DEV
State: {stage: DEV, attempt: 1, rollback_history: [...]}
  ↓ DEV fixes issues
State: {stage: TEST, attempt: 1}
  ↓ ... continues
```

## Completed Tasks

When a task completes, it's archived:

```
galangal-tasks/done/add-user-auth/
├── state.json
├── SPEC.md
└── ... (all artifacts)
```

## State Recovery

If state becomes corrupted, you can:

1. Edit `state.json` directly
2. Use `galangal reset` to restart the task
3. Manually set stage with careful editing

## Related Documentation

- [Architecture](architecture.md) - System overview
- [Workflow Pipeline](workflow-pipeline.md) - Stage execution
- [CLI Commands](cli-commands.md) - Command reference
