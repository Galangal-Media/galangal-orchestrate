# System Architecture

This document describes the overall architecture of Galangal Orchestrate and how its components interact.

## Overview

Galangal Orchestrate is an AI-driven development workflow orchestrator that guides AI assistants through a structured, deterministic 13-stage development pipeline. It wraps Claude Code CLI to execute complex development tasks with approval gates, automatic validation, and rollback mechanisms.

## Directory Structure

```
src/galangal/
├── __init__.py                    # Version & exports
├── cli.py                         # CLI entry point (lazy imports)
├── exceptions.py                  # Custom exceptions
├── logging.py                     # Structured logging
├── results.py                     # Result types & enums
│
├── ai/                            # AI backend abstraction
│   ├── base.py                    # Abstract AIBackend base class
│   ├── claude.py                  # Claude CLI backend
│   └── gemini.py                  # Gemini backend (planned)
│
├── config/                        # Configuration management
│   ├── schema.py                  # Pydantic models
│   ├── loader.py                  # Config loading & caching
│   └── defaults.py                # Default configuration
│
├── core/                          # Core workflow logic
│   ├── state.py                   # Stage, TaskType, WorkflowState
│   ├── tasks.py                   # Task directory management
│   ├── artifacts.py               # Artifact I/O utilities
│   └── workflow/
│       ├── core.py                # Stage execution & validation
│       ├── tui_runner.py          # TUI-based workflow runner
│       └── pause.py               # Pause/resume logic
│
├── commands/                      # CLI command implementations
│   ├── start.py                   # Start new tasks
│   ├── resume.py                  # Resume paused tasks
│   ├── approve.py                 # Approval commands
│   ├── skip.py                    # Skip stage commands
│   ├── complete.py                # Completion & PR creation
│   ├── status.py                  # Status display
│   └── ...                        # Other commands
│
├── prompts/                       # Prompt system
│   ├── builder.py                 # PromptBuilder class
│   └── defaults/                  # Default stage prompts
│       ├── pm.md
│       ├── design.md
│       ├── dev.md
│       └── ...                    # Other stage prompts
│
├── validation/                    # Validation system
│   └── runner.py                  # ValidationRunner class
│
└── ui/                            # User interface
    ├── console.py                 # Legacy console output
    └── tui/                       # Textual TUI
        ├── app.py                 # WorkflowTUIApp
        ├── widgets.py             # Custom widgets
        ├── modals.py              # Modal dialogs
        └── entry.py               # Entry point
```

## Core Components

### 1. CLI Layer (`cli.py`)

The CLI entry point uses lazy imports for fast startup:

```python
def main() -> int:
    # Fast argument parsing
    # Lazy imports only when command executes
```

Each command is implemented in a separate module under `commands/` to minimize import overhead.

### 2. Workflow Engine (`core/workflow/`)

The workflow engine orchestrates stage execution:

- **`core.py`**: Contains `execute_stage()` which runs a single stage
- **`tui_runner.py`**: Contains `_run_workflow_with_tui()` which loops through stages
- **`pause.py`**: Handles Ctrl+C pause signals and graceful termination

### 3. AI Backend (`ai/`)

Abstraction layer for AI providers:

```
AIBackend (base.py)
    ├── ClaudeBackend (claude.py) - Primary implementation
    └── GeminiBackend (gemini.py) - Future support
```

The `ClaudeBackend`:
- Invokes `claude` CLI with streaming JSON output
- Parses tool use events in real-time
- Updates TUI with activity status
- Supports graceful pause via callback

### 4. State Management (`core/state.py`)

Defines the workflow state model:

- `Stage` enum: 13 workflow stages with metadata
- `TaskType` enum: 6 task types (feature, bug_fix, etc.)
- `WorkflowState` dataclass: Persistent task state

### 5. Prompt System (`prompts/`)

Builds prompts by merging:
1. Base prompts from `prompts/defaults/`
2. Project overrides from `.galangal/prompts/`
3. Task context (name, type, artifacts)
4. Config context

### 6. Validation System (`validation/runner.py`)

Runs config-driven validation:
- Skip condition checks
- Shell command execution
- Artifact marker verification
- Required file checks

### 7. TUI (`ui/tui/`)

Textual-based terminal UI showing:
- Stage progress
- Activity log
- Prompts and confirmations

## Data Flow

```
User Command → CLI
                ↓
            WorkflowRunner
                ↓
    ┌───────────────────────┐
    │   Stage Loop          │
    │   ├─ PromptBuilder    │
    │   ├─ ClaudeBackend    │
    │   ├─ ValidationRunner │
    │   └─ State Persistence│
    └───────────────────────┘
                ↓
            TUI Updates
```

## File System Layout

### Project Configuration

```
.galangal/
├── config.yaml            # Workflow configuration
├── prompts/               # Project prompt overrides
│   ├── pm.md
│   ├── dev.md
│   └── ...
└── active_task            # Current active task name
```

### Task Storage

```
galangal-tasks/
├── <task-name>/
│   ├── state.json         # WorkflowState
│   ├── SPEC.md            # PM output
│   ├── PLAN.md            # PM output
│   ├── DESIGN.md          # Design output
│   ├── DEVELOPMENT.md     # Dev progress
│   ├── ROLLBACK.md        # Issues to fix
│   └── logs/
│       ├── pm_1.log
│       ├── dev_1.log
│       └── ...
└── done/                  # Completed tasks
```

## Threading Model

The TUI uses a specific threading model:

```
Main Thread: Textual Event Loop
    ↓
    └─ Async Worker (run_worker())
        ├─ PM Discovery Q&A
        └─ Stage Loop
            └─ Thread Executor (blocking Claude calls)
```

- Textual runs in the main thread
- Workflow logic runs in an async worker
- Blocking Claude CLI calls use thread executors
- State updates happen via TUI callbacks

## Key Design Decisions

### 1. Deterministic Pipeline

The 13-stage pipeline is fixed and deterministic. Stages cannot be reordered, but can be skipped based on:
- Configuration
- Task type
- Runtime conditions

### 2. Artifact-Centric

Each stage produces artifacts (markdown files) that become context for subsequent stages. This enables:
- Resume from any point
- Rollback with context preservation
- Human-readable audit trail

### 3. Configuration-Driven Validation

Validation logic is entirely config-driven, not hardcoded. This allows:
- Project-specific validation rules
- Easy customization without code changes
- Declarative validation definitions

### 4. Graceful Degradation

The system handles failures gracefully:
- Retry with failure context in prompt
- Rollback to appropriate stage
- Loop prevention for rollbacks
- Manual intervention when automated recovery fails

## Related Documentation

- [Workflow Pipeline](workflow-pipeline.md) - Stage execution details
- [State Management](state-management.md) - State persistence
- [Prompt System](prompt-system.md) - Prompt building
- [Validation System](validation-system.md) - Validation rules
- [Configuration](configuration.md) - Config options
