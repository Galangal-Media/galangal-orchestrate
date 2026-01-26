"""
Schema models for artifact validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SectionSpec:
    """Specification for a single section in an artifact schema."""

    name: str
    required: bool = True
    description: str = ""
    # Future extensions: min_words, min_items, format, etc.

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any] | bool) -> SectionSpec:
        """Create from dictionary or bool shorthand.

        Supports:
            sections:
              overview: true           # shorthand for required
              constraints: false       # shorthand for optional
              requirements:            # full spec
                required: true
                description: "..."
        """
        if isinstance(d, bool):
            return cls(name=name, required=d)
        return cls(
            name=name,
            required=d.get("required", True),
            description=d.get("description", ""),
        )


@dataclass
class ArtifactSchema:
    """Schema definition for an artifact type."""

    artifact: str  # e.g., "SPEC.md"
    produced_by: str = ""  # e.g., "PM"
    sections: dict[str, SectionSpec] = field(default_factory=dict)
    task_type_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ArtifactSchema:
        """Create from dictionary (parsed YAML)."""
        sections = {}
        for name, spec in d.get("sections", {}).items():
            sections[name] = SectionSpec.from_dict(name, spec)

        return cls(
            artifact=d.get("artifact", ""),
            produced_by=d.get("produced_by", ""),
            sections=sections,
            task_type_overrides=d.get("task_type_overrides", {}),
        )

    def get_sections_for_task_type(self, task_type: str) -> dict[str, SectionSpec]:
        """Get sections with task type overrides applied.

        Args:
            task_type: Task type value (e.g., "feature", "bug_fix").

        Returns:
            Sections dict with overrides merged in.
        """
        # Start with base sections
        result = dict(self.sections)

        # Apply task type overrides
        overrides = self.task_type_overrides.get(task_type, {})
        override_sections = overrides.get("sections", {})

        for name, spec_data in override_sections.items():
            if name in result:
                # Merge override with existing
                base = result[name]
                override = SectionSpec.from_dict(name, spec_data)
                result[name] = SectionSpec(
                    name=name,
                    required=override.required if spec_data else base.required,
                    description=override.description or base.description,
                )
            else:
                # New section from override
                result[name] = SectionSpec.from_dict(name, spec_data)

        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "artifact": self.artifact,
            "produced_by": self.produced_by,
            "sections": {
                name: {"required": spec.required, "description": spec.description}
                for name, spec in self.sections.items()
            },
            "task_type_overrides": self.task_type_overrides,
        }


@dataclass
class SectionValidationResult:
    """Validation result for a single section."""

    name: str
    present: bool
    empty: bool = False
    error: str | None = None
    warning: str | None = None


@dataclass
class SchemaResult:
    """Result of validating an artifact against its schema."""

    valid: bool
    artifact: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    section_results: list[SectionValidationResult] = field(default_factory=list)

    def format_feedback(self) -> str:
        """Format validation result as feedback for AI retry.

        Returns:
            Human-readable feedback string.
        """
        lines = []

        if self.errors:
            lines.append(f"{self.artifact} schema validation failed:")
            for error in self.errors:
                lines.append(f"  - {error}")

        if self.warnings:
            if lines:
                lines.append("")
            lines.append("Warnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        if self.errors:
            lines.append("")
            lines.append("Please revise the artifact to address these issues.")

        return "\n".join(lines)
