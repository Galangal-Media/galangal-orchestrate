# Mistake Tracking System

The mistake tracking system is a learning feature that records common AI mistakes in your codebase and prevents them from recurring. It uses vector embeddings for semantic similarity matching and automatically deduplicates similar mistakes.

## Overview

When a stage fails validation or a user interrupts with feedback, the system:
1. Records the mistake with an embedding
2. Deduplicates against existing similar mistakes
3. Injects warnings into future prompts for the same stage

This creates a feedback loop where the AI learns from past failures in your specific codebase.

## Database Location

```
.galangal/mistakes.db
```

The SQLite database is created automatically on first use. It includes a vector search extension (sqlite-vss) for fast semantic similarity queries.

## Core Components

### Files

| File | Purpose |
|------|---------|
| `src/galangal/mistakes.py` | `MistakeTracker` class and `Mistake` dataclass |
| `src/galangal/commands/mistakes.py` | CLI commands for managing mistakes |
| `src/galangal/core/workflow/core.py` | Logs mistakes on rollback |
| `src/galangal/core/workflow/engine.py` | Logs mistakes on user interrupt |
| `src/galangal/prompts/builder.py` | Injects warnings into prompts |

### Dependencies

```toml
# In pyproject.toml (core dependencies)
"sentence-transformers>=2.2.0"  # Local embeddings
"sqlite-vss>=0.1.2"             # Vector search extension
```

The embedding model (`all-MiniLM-L6-v2`) runs locally with no API calls.

## Database Schema

### Main Table: `mistakes`

```sql
CREATE TABLE mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,        -- What went wrong
    feedback TEXT NOT NULL,           -- How to fix/prevent it
    stage TEXT NOT NULL,              -- Stage where mistake occurred
    file_patterns TEXT NOT NULL,      -- JSON array of file patterns
    occurrence_count INTEGER DEFAULT 1,
    last_task TEXT NOT NULL,
    last_timestamp INTEGER NOT NULL,
    example_tasks TEXT NOT NULL,      -- JSON array (max 5)
    embedding BLOB                    -- 384-dim vector
)
```

### Vector Search Table: `mistakes_vss`

```sql
CREATE VIRTUAL TABLE mistakes_vss USING vss0(
    embedding(384)
)
```

If sqlite-vss is unavailable, the system falls back to Python-based cosine distance calculation.

## How Mistakes Are Recorded

### Trigger 1: Stage Rollback

When a stage fails validation and rolls back, the failure reason is logged:

```python
# In core/workflow/core.py
def _log_mistake_from_rollback(task_name: str, stage: str, reason: str) -> None:
    tracker = MistakeTracker()
    tracker.log(
        description=reason.split(".")[0],  # First sentence
        feedback=reason,
        stage=stage,
        task=task_name,
    )
```

### Trigger 2: User Interrupt (Ctrl+I)

When a user interrupts with feedback, that feedback is logged:

```python
# In core/workflow/engine.py
def _log_interrupt_mistake(self, task_name: str, stage: str, feedback: str) -> None:
    if not feedback.strip():
        return
    tracker = MistakeTracker()
    tracker.log(
        description=feedback,
        feedback=feedback,
        stage=stage,
        task=task_name,
    )
```

### Deduplication

When logging, the system searches for similar existing mistakes:

```python
def log(self, description, feedback, stage, task, files=None) -> int:
    embedding = self._embed(f"{description} {feedback}")
    similar = self._find_similar(embedding, stage, threshold=0.3)

    if similar:
        # Merge with existing mistake
        existing = similar[0]
        existing.occurrence_count += 1
        existing.example_tasks.append(task)  # Keep last 5
        return existing.id
    else:
        # Insert new mistake
        return self._insert(description, feedback, stage, task, files, embedding)
```

The deduplication threshold (0.3 cosine distance) catches semantically similar mistakes even with different wording.

## How Warnings Are Injected

During prompt building, relevant mistakes are retrieved and formatted:

```python
# In prompts/builder.py
def _get_mistake_warnings(stage: Stage, state: WorkflowState) -> str:
    try:
        tracker = MistakeTracker()
        return tracker.format_warnings_for_prompt(
            stage=stage.value,
            task_description=state.task_description,
        )
    except ImportError:
        return ""  # Graceful degradation
```

### Warning Format

```markdown
# Common Mistakes in This Repo - AVOID THESE

The following mistakes have occurred before in this codebase:

## 1. Forgot null check on user object
**Occurrences:** 3 times
**Files:** src/auth/*.py
**Prevention:** Always check if user exists before accessing properties

## 2. Missing error handling in API calls
**Occurrences:** 2 times
**Prevention:** Wrap all fetch calls in try/catch
```

### Retrieval Priority

Mistakes are ranked by:
1. Occurrence count (most frequent first)
2. Recency (most recent first)
3. File pattern matches (if files being changed match)
4. Semantic similarity to task description

Maximum 5 warnings are included per prompt.

## CLI Commands

### List Mistakes

```bash
galangal mistakes list              # Show 20 most recent
galangal mistakes list --limit 50   # Show up to 50
galangal mistakes list --stage DEV  # Filter by stage
```

Output:
```
ID  Stage  Count  Description                    Last Task        Age
──  ─────  ─────  ───────────────────────────    ─────────────    ───
42  DEV    5      Forgot null check              auth-feature     2d
38  TEST   3      Missing mock for API calls     api-refactor     5d
35  DEV    2      Hardcoded config values        config-update    1w
```

### View Statistics

```bash
galangal mistakes stats
```

Output:
```
Mistake Tracking Statistics

Unique mistakes     12
Total occurrences   47
Vector search       Enabled

By Stage:
Stage    Count
DEV      8
TEST     3
PM       1
```

### Search Mistakes

```bash
galangal mistakes search "null check"
```

Uses vector search to find semantically similar mistakes (threshold 0.7).

### Delete a Mistake

```bash
galangal mistakes delete 42
```

Requires confirmation before deletion.

## Configuration

### Constants

```python
# In mistakes.py
EMBEDDING_DIM = 384           # all-MiniLM-L6-v2 dimension
DEDUP_THRESHOLD = 0.3         # Cosine distance for deduplication
MAX_PROMPT_WARNINGS = 5       # Max warnings in prompts
```

### Database Path Override

```python
# For testing or custom locations
tracker = MistakeTracker(db_path=Path("/custom/path/mistakes.db"))
```

## Graceful Degradation

The system never blocks the workflow:

| Condition | Behavior |
|-----------|----------|
| sentence-transformers not installed | Feature disabled, silent skip |
| sqlite-vss not available | Falls back to Python-based similarity |
| Error during logging | Caught and ignored |
| Error during retrieval | Returns empty string (no warnings) |

## Embedding Details

### Model

- **Name:** `all-MiniLM-L6-v2`
- **Dimension:** 384
- **Normalization:** Embeddings are L2-normalized
- **Latency:** ~50ms per embedding
- **Initialization:** Lazy (only loaded when first used)

### Similarity Calculation

For normalized vectors, cosine distance = 1 - dot product:

```python
def _cosine_distance(self, a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return 1 - dot
```

Distance scale:
- `0.0` = Identical
- `0.3` = Deduplication threshold (very similar)
- `0.7` = Search threshold (somewhat similar)
- `1.0` = Completely different

## Data Flow Example

```
1. User presses Ctrl+I with feedback: "AI forgot null check"
   ↓
2. engine.py calls _log_interrupt_mistake()
   ↓
3. MistakeTracker.log() is invoked
   ↓
4. Text embedded → [0.234, -0.512, ..., 0.891]
   ↓
5. Vector search for similar DEV mistakes
   ↓
6. If similar found (distance < 0.3): merge
   If new: insert with embedding
   ↓
7. [Later] New DEV stage starts
   ↓
8. prompts/builder.py calls _get_mistake_warnings()
   ↓
9. format_warnings_for_prompt() retrieves top 5 relevant mistakes
   ↓
10. Warnings injected into prompt
    ↓
11. AI sees warning before executing stage
```

## Verification

Check mistake tracking status:

```bash
galangal doctor
```

Output includes:
```
✓ Mistake tracking: Enabled
```

Or if unavailable:
```
⚠ Mistake tracking: Not installed
```

## Performance

| Operation | Typical Latency |
|-----------|-----------------|
| Embedding generation | ~50ms |
| Vector search (with VSS) | <10ms |
| Vector search (fallback) | <200ms |
| Full database (1000 mistakes) | ~3MB |

The database is lightweight and local. No external API calls are made.
