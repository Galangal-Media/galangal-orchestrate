"""
Artifact lineage tracking with section-level hashing.

Tracks dependencies between artifacts and stages to detect when upstream
changes should invalidate downstream stages.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from galangal.config.schema import LineageConfig
    from galangal.core.state import WorkflowState


@dataclass
class ArtifactLineage:
    """Lineage information for a single artifact.

    Tracks when and by which stage an artifact was generated,
    along with section-level hashes for change detection.
    """

    artifact_name: str
    generated_at: str  # ISO timestamp
    generated_by_stage: str
    section_hashes: dict[str, str]  # section_name -> sha256[:16]
    input_hashes: dict[str, dict[str, str]]  # upstream_artifact -> {section -> hash}
    depends_on: dict[str, list[str]]  # upstream_artifact -> [sections]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ArtifactLineage:
        """Create from dictionary."""
        return cls(
            artifact_name=d["artifact_name"],
            generated_at=d["generated_at"],
            generated_by_stage=d["generated_by_stage"],
            section_hashes=d.get("section_hashes", {}),
            input_hashes=d.get("input_hashes", {}),
            depends_on=d.get("depends_on", {}),
        )


@dataclass
class StageLineage:
    """Lineage information for a stage completion.

    Tracks when a stage completed and what artifact states it consumed.
    """

    stage: str
    completed_at: str  # ISO timestamp
    input_hashes: dict[str, dict[str, str]]  # artifact -> {section -> hash}
    depends_on_stages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StageLineage:
        """Create from dictionary."""
        return cls(
            stage=d["stage"],
            completed_at=d["completed_at"],
            input_hashes=d.get("input_hashes", {}),
            depends_on_stages=d.get("depends_on_stages", []),
        )


# Default artifact dependencies - which artifacts depend on which upstream artifacts
DEFAULT_ARTIFACT_DEPS: dict[str, list[dict[str, Any]]] = {
    "DESIGN.md": [
        {"artifact": "SPEC.md", "sections": ["requirements", "constraints", "acceptance-criteria"]}
    ],
    "PLAN.md": [
        {"artifact": "SPEC.md", "sections": ["requirements"]},
        {"artifact": "DESIGN.md", "sections": ["architecture", "components"]},
    ],
}

# Default stage dependencies - which stages depend on which artifacts/stages
DEFAULT_STAGE_DEPS: dict[str, dict[str, Any]] = {
    "DEV": {
        "depends_on_artifacts": [
            {"artifact": "PLAN.md", "sections": ["implementation-steps", "file-changes"]},
        ],
    },
    "TEST": {
        "depends_on_stages": ["DEV"],
        "depends_on_artifacts": [
            {"artifact": "SPEC.md", "sections": ["acceptance-criteria"]}
        ],
    },
    "QA": {
        "depends_on_stages": ["DEV", "TEST"],
        "depends_on_artifacts": [
            {"artifact": "SPEC.md", "sections": ["acceptance-criteria"]}
        ],
    },
    "REVIEW": {"depends_on_stages": ["DEV", "TEST", "QA"]},
    "DOCS": {"depends_on_stages": ["DEV"]},
}


class LineageTracker:
    """Tracks artifact lineage for staleness detection.

    Provides methods to:
    - Parse markdown into section hashes
    - Record artifact/stage lineage after completion
    - Check if artifacts/stages are fresh (inputs unchanged)
    - Detect external modifications to artifacts
    - Preview cascade of stages that would re-run
    """

    def __init__(self, config: LineageConfig):
        """Initialize the tracker with lineage configuration.

        Args:
            config: LineageConfig with dependency specifications.
        """
        self.config = config
        self._artifact_deps = self._build_artifact_deps()
        self._stage_deps = self._build_stage_deps()

    def _build_artifact_deps(self) -> dict[str, list[dict[str, Any]]]:
        """Build merged artifact dependencies from defaults and config."""
        deps = dict(DEFAULT_ARTIFACT_DEPS)
        for artifact, dep_specs in self.config.artifact_dependencies.items():
            deps[artifact] = [
                {"artifact": spec.artifact, "sections": spec.sections}
                for spec in dep_specs
            ]
        return deps

    def _build_stage_deps(self) -> dict[str, dict[str, Any]]:
        """Build merged stage dependencies from defaults and config."""
        deps = dict(DEFAULT_STAGE_DEPS)
        for stage, stage_config in self.config.stage_dependencies.items():
            deps[stage.upper()] = {
                "depends_on_stages": stage_config.depends_on_stages,
                "depends_on_artifacts": [
                    {"artifact": spec.artifact, "sections": spec.sections}
                    for spec in stage_config.depends_on_artifacts
                ],
            }
        return deps

    def parse_sections(self, content: str) -> dict[str, str]:
        """Parse markdown into section name -> hash mapping.

        Sections are identified by markdown headers (lines starting with #).
        The section name is normalized (lowercase, hyphenated, stripped).
        Each section includes its header line and all content until the next header.

        Content without any headers is assigned to a 'preamble' section.

        Args:
            content: Markdown content to parse.

        Returns:
            Dict mapping normalized section names to content hashes.
        """
        sections: dict[str, str] = {}
        current = "preamble"
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("#"):
                # Save previous section
                if current_lines:
                    sections[current] = self._hash("\n".join(current_lines))
                # Start new section - extract header text after #'s
                header_text = line.lstrip("#").strip()
                current = self._normalize(header_text)
                current_lines = [line]
            else:
                current_lines.append(line)

        # Save final section
        if current_lines:
            sections[current] = self._hash("\n".join(current_lines))

        return sections

    def _normalize(self, name: str) -> str:
        """Normalize a section name for consistent matching.

        Converts to lowercase, replaces spaces with hyphens, strips whitespace.

        Args:
            name: Section name to normalize.

        Returns:
            Normalized section name.
        """
        return name.lower().strip().replace(" ", "-")

    def _hash(self, content: str) -> str:
        """Hash content with whitespace normalization.

        Normalizes whitespace to make hashes stable across minor formatting changes.
        Returns first 16 characters of SHA256 hash.

        Args:
            content: Content to hash.

        Returns:
            16-character hash string.
        """
        normalized = re.sub(r"\s+", " ", content.strip())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def record_artifact(
        self,
        name: str,
        content: str,
        stage: str,
        task_name: str,
        state: WorkflowState,
    ) -> None:
        """Record lineage after artifact creation.

        Computes section hashes for the artifact and records which upstream
        artifacts (and their hashes) were used as inputs.

        Args:
            name: Artifact filename.
            content: Artifact content.
            stage: Stage that generated this artifact.
            task_name: Name of the task.
            state: WorkflowState to update with lineage info.
        """
        section_hashes = self.parse_sections(content)
        deps = self._artifact_deps.get(name, [])

        # Collect input hashes from upstream artifacts
        input_hashes: dict[str, dict[str, str]] = {}
        depends_on: dict[str, list[str]] = {}

        for dep in deps:
            upstream_name = dep["artifact"]
            upstream_sections = dep.get("sections", [])

            if upstream_name in state.artifact_lineage:
                upstream_lineage = state.artifact_lineage[upstream_name]
                if upstream_sections:
                    # Only track specified sections
                    input_hashes[upstream_name] = {
                        sec: upstream_lineage.section_hashes.get(sec, "")
                        for sec in upstream_sections
                        if sec in upstream_lineage.section_hashes
                    }
                else:
                    # Track all sections
                    input_hashes[upstream_name] = dict(upstream_lineage.section_hashes)
                depends_on[upstream_name] = upstream_sections or list(
                    upstream_lineage.section_hashes.keys()
                )

        lineage = ArtifactLineage(
            artifact_name=name,
            generated_at=datetime.now(timezone.utc).isoformat(),
            generated_by_stage=stage,
            section_hashes=section_hashes,
            input_hashes=input_hashes,
            depends_on=depends_on,
        )

        state.artifact_lineage[name] = lineage

    def record_stage(
        self,
        stage: str,
        artifacts: dict[str, str],
        state: WorkflowState,
    ) -> None:
        """Record stage completion with input hashes.

        Args:
            stage: Stage name that completed.
            artifacts: Dict of artifact_name -> content for current artifacts.
            state: WorkflowState to update with stage lineage.
        """
        stage_upper = stage.upper()
        deps = self._stage_deps.get(stage_upper, {})
        artifact_deps = deps.get("depends_on_artifacts", [])
        stage_deps = deps.get("depends_on_stages", [])

        # Collect input hashes from artifacts this stage depends on
        input_hashes: dict[str, dict[str, str]] = {}

        for dep in artifact_deps:
            artifact_name = dep["artifact"]
            sections = dep.get("sections", [])

            if artifact_name in artifacts:
                content_hashes = self.parse_sections(artifacts[artifact_name])
                if sections:
                    input_hashes[artifact_name] = {
                        sec: content_hashes.get(sec, "")
                        for sec in sections
                        if sec in content_hashes
                    }
                else:
                    input_hashes[artifact_name] = content_hashes

        lineage = StageLineage(
            stage=stage_upper,
            completed_at=datetime.now(timezone.utc).isoformat(),
            input_hashes=input_hashes,
            depends_on_stages=stage_deps,
        )

        state.stage_lineage[stage_upper] = lineage

    def check_artifact_fresh(
        self,
        name: str,
        current_artifacts: dict[str, str],
        state: WorkflowState,
    ) -> tuple[bool, list[str]]:
        """Check if an artifact's inputs are unchanged.

        Compares current hashes of upstream artifacts against the hashes
        recorded when this artifact was generated.

        Args:
            name: Artifact filename to check.
            current_artifacts: Dict of artifact_name -> content.
            state: WorkflowState with lineage information.

        Returns:
            (is_fresh, reasons) - True if fresh, list of change reasons if stale.
        """
        if name not in state.artifact_lineage:
            return True, []  # No lineage recorded - assume fresh

        lineage = state.artifact_lineage[name]
        reasons: list[str] = []

        for upstream_name, recorded_hashes in lineage.input_hashes.items():
            if upstream_name not in current_artifacts:
                reasons.append(f"{upstream_name} is missing")
                continue

            current_hashes = self.parse_sections(current_artifacts[upstream_name])
            tracked_sections = lineage.depends_on.get(upstream_name, [])

            for section in tracked_sections:
                recorded = recorded_hashes.get(section, "")
                current = current_hashes.get(section, "")
                if recorded and current and recorded != current:
                    reasons.append(f"{upstream_name}#{section} changed")

        return len(reasons) == 0, reasons

    def check_stage_fresh(
        self,
        stage: str,
        current_artifacts: dict[str, str],
        state: WorkflowState,
    ) -> tuple[bool, list[str]]:
        """Check if a stage's inputs are unchanged.

        Args:
            stage: Stage name to check.
            current_artifacts: Dict of artifact_name -> content.
            state: WorkflowState with lineage information.

        Returns:
            (is_fresh, reasons) - True if fresh, list of change reasons if stale.
        """
        stage_upper = stage.upper()
        if stage_upper not in state.stage_lineage:
            return True, []  # No lineage recorded - assume fresh

        lineage = state.stage_lineage[stage_upper]
        reasons: list[str] = []

        # Check artifact dependencies
        for artifact_name, recorded_hashes in lineage.input_hashes.items():
            if artifact_name not in current_artifacts:
                reasons.append(f"{artifact_name} is missing")
                continue

            current_hashes = self.parse_sections(current_artifacts[artifact_name])

            for section, recorded_hash in recorded_hashes.items():
                current_hash = current_hashes.get(section, "")
                if recorded_hash and current_hash and recorded_hash != current_hash:
                    reasons.append(f"{artifact_name}#{section} changed")

        # Check stage dependencies (have they re-run since we completed?)
        for dep_stage in lineage.depends_on_stages:
            if dep_stage in state.stage_lineage:
                dep_lineage = state.stage_lineage[dep_stage]
                # If dependency completed after us, we're stale
                if dep_lineage.completed_at > lineage.completed_at:
                    reasons.append(f"{dep_stage} re-ran after {stage_upper}")

        return len(reasons) == 0, reasons

    def detect_external_mods(
        self,
        task_name: str,
        current_artifacts: dict[str, str],
        state: WorkflowState,
    ) -> dict[str, list[str]]:
        """Detect artifacts modified outside the workflow.

        Compares current artifact hashes against recorded hashes to find
        changes made externally (e.g., manual edits).

        Args:
            task_name: Name of the task.
            current_artifacts: Dict of artifact_name -> content.
            state: WorkflowState with lineage information.

        Returns:
            Dict mapping modified artifact names to list of changed sections.
        """
        modifications: dict[str, list[str]] = {}

        for name, lineage in state.artifact_lineage.items():
            if name not in current_artifacts:
                continue

            current_hashes = self.parse_sections(current_artifacts[name])
            changed_sections: list[str] = []

            for section, recorded_hash in lineage.section_hashes.items():
                current_hash = current_hashes.get(section, "")
                if recorded_hash and current_hash and recorded_hash != current_hash:
                    changed_sections.append(section)

            # Also check for new sections
            for section in current_hashes:
                if section not in lineage.section_hashes:
                    changed_sections.append(f"{section} (new)")

            if changed_sections:
                modifications[name] = changed_sections

        return modifications

    def get_cascade_preview(
        self,
        state: WorkflowState,
        current_artifacts: dict[str, str],
    ) -> list[tuple[str, list[str]]]:
        """Preview stages that will re-run due to staleness.

        Args:
            state: WorkflowState with lineage information.
            current_artifacts: Dict of artifact_name -> content.

        Returns:
            List of (stage_name, reasons) tuples for stale stages.
        """
        from galangal.core.state import STAGE_ORDER

        cascade: list[tuple[str, list[str]]] = []

        for stage in STAGE_ORDER:
            stage_name = stage.value
            if stage_name in state.stage_lineage:
                is_fresh, reasons = self.check_stage_fresh(
                    stage_name, current_artifacts, state
                )
                if not is_fresh:
                    cascade.append((stage_name, reasons))

        return cascade


def load_task_artifacts(task_name: str) -> dict[str, str]:
    """Load all artifacts for a task.

    Args:
        task_name: Name of the task.

    Returns:
        Dict mapping artifact names to their content.
    """
    from galangal.core.state import get_task_dir

    task_dir = get_task_dir(task_name)
    artifacts: dict[str, str] = {}

    if not task_dir.exists():
        return artifacts

    for path in task_dir.iterdir():
        if path.is_file() and path.suffix == ".md":
            try:
                artifacts[path.name] = path.read_text()
            except OSError:
                pass  # Skip unreadable files

    return artifacts
