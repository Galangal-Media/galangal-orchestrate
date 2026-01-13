"""
Project metrics tracking for learning and adaptation.

Tracks stage success/failure rates, common failure patterns, and
other metrics that can be used to improve workflow behavior.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from galangal.core.state import Stage


@dataclass
class StageRun:
    """Record of a single stage execution."""

    timestamp: str
    success: bool
    attempts: int
    turns_used: int | None = None
    failure_reason: str | None = None
    task_type: str | None = None

    def to_dict(self) -> dict:
        d = {
            "timestamp": self.timestamp,
            "success": self.success,
            "attempts": self.attempts,
        }
        if self.turns_used is not None:
            d["turns_used"] = self.turns_used
        if self.failure_reason:
            d["failure_reason"] = self.failure_reason
        if self.task_type:
            d["task_type"] = self.task_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StageRun":
        return cls(
            timestamp=d["timestamp"],
            success=d["success"],
            attempts=d.get("attempts", 1),
            turns_used=d.get("turns_used"),
            failure_reason=d.get("failure_reason"),
            task_type=d.get("task_type"),
        )


@dataclass
class StageMetrics:
    """Aggregated metrics for a single stage."""

    runs: list[StageRun] = field(default_factory=list)

    @property
    def total_runs(self) -> int:
        return len(self.runs)

    @property
    def successes(self) -> int:
        return sum(1 for r in self.runs if r.success)

    @property
    def failures(self) -> int:
        return sum(1 for r in self.runs if not r.success)

    @property
    def success_rate(self) -> float:
        if not self.runs:
            return 0.0
        return self.successes / len(self.runs)

    @property
    def failure_rate(self) -> float:
        if not self.runs:
            return 0.0
        return self.failures / len(self.runs)

    @property
    def avg_attempts(self) -> float:
        if not self.runs:
            return 0.0
        return sum(r.attempts for r in self.runs) / len(self.runs)

    @property
    def avg_turns(self) -> float | None:
        turns = [r.turns_used for r in self.runs if r.turns_used is not None]
        if not turns:
            return None
        return sum(turns) / len(turns)

    def common_failures(self, limit: int = 5) -> list[tuple[str, int]]:
        """Get the most common failure reasons.

        Returns list of (reason, count) tuples, sorted by count descending.
        """
        reasons = [r.failure_reason for r in self.runs if r.failure_reason]
        if not reasons:
            return []
        counter = Counter(reasons)
        return counter.most_common(limit)

    def to_dict(self) -> dict:
        return {"runs": [r.to_dict() for r in self.runs]}

    @classmethod
    def from_dict(cls, d: dict) -> "StageMetrics":
        return cls(runs=[StageRun.from_dict(r) for r in d.get("runs", [])])


@dataclass
class ProjectMetrics:
    """All metrics for a project."""

    stages: dict[str, StageMetrics] = field(default_factory=dict)
    version: int = 1  # Schema version for future migrations

    def get_stage(self, stage: Stage | str) -> StageMetrics:
        """Get metrics for a stage, creating if needed."""
        stage_name = stage.value if isinstance(stage, Stage) else stage
        if stage_name not in self.stages:
            self.stages[stage_name] = StageMetrics()
        return self.stages[stage_name]

    def record_run(
        self,
        stage: Stage | str,
        success: bool,
        attempts: int = 1,
        turns_used: int | None = None,
        failure_reason: str | None = None,
        task_type: str | None = None,
    ) -> None:
        """Record a stage execution result."""
        stage_metrics = self.get_stage(stage)
        run = StageRun(
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=success,
            attempts=attempts,
            turns_used=turns_used,
            failure_reason=_normalize_failure_reason(failure_reason) if failure_reason else None,
            task_type=task_type,
        )
        stage_metrics.runs.append(run)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "stages": {name: metrics.to_dict() for name, metrics in self.stages.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectMetrics":
        return cls(
            version=d.get("version", 1),
            stages={
                name: StageMetrics.from_dict(data)
                for name, data in d.get("stages", {}).items()
            },
        )


def _normalize_failure_reason(reason: str, max_length: int = 200) -> str:
    """Normalize a failure reason for aggregation.

    - Truncate to reasonable length
    - Strip file paths and line numbers to group similar errors
    - Remove timestamps and unique identifiers
    """
    # Truncate
    if len(reason) > max_length:
        reason = reason[:max_length] + "..."

    # Take first line only (often most meaningful)
    first_line = reason.split("\n")[0].strip()
    if first_line:
        return first_line

    return reason


def get_metrics_path() -> Path:
    """Get the path to the metrics file."""
    from galangal.config.loader import get_project_root

    return get_project_root() / ".galangal" / "metrics.yaml"


def load_metrics() -> ProjectMetrics:
    """Load project metrics from file."""
    path = get_metrics_path()
    if not path.exists():
        return ProjectMetrics()

    try:
        data = yaml.safe_load(path.read_text()) or {}
        return ProjectMetrics.from_dict(data)
    except (yaml.YAMLError, KeyError, TypeError) as e:
        # If metrics file is corrupted, start fresh
        print(f"Warning: Could not load metrics ({e}), starting fresh")
        return ProjectMetrics()


def save_metrics(metrics: ProjectMetrics) -> None:
    """Save project metrics to file."""
    path = get_metrics_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(metrics.to_dict(), default_flow_style=False, sort_keys=False))


def record_stage_result(
    stage: Stage | str,
    success: bool,
    attempts: int = 1,
    turns_used: int | None = None,
    failure_reason: str | None = None,
    task_type: str | None = None,
) -> None:
    """Record a stage execution result (convenience function).

    This is the main entry point for recording metrics. Call this after
    each stage completes (success or failure).
    """
    metrics = load_metrics()
    metrics.record_run(
        stage=stage,
        success=success,
        attempts=attempts,
        turns_used=turns_used,
        failure_reason=failure_reason,
        task_type=task_type,
    )
    save_metrics(metrics)


def get_common_failures_for_prompt(stage: Stage | str, limit: int = 3) -> str | None:
    """Get formatted common failures for injection into a stage prompt.

    Returns None if no significant failure patterns exist.
    """
    metrics = load_metrics()
    stage_metrics = metrics.get_stage(stage)

    # Only show if we have enough data and a meaningful failure rate
    if stage_metrics.total_runs < 5 or stage_metrics.failure_rate < 0.2:
        return None

    common = stage_metrics.common_failures(limit)
    if not common:
        return None

    # Format for prompt injection
    lines = ["## Common Issues in This Project", ""]
    lines.append("This stage has historically had issues with:")
    for reason, count in common:
        lines.append(f"- {reason}")

    return "\n".join(lines)
