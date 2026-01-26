"""
Artifact schema validation.
"""

from __future__ import annotations

from galangal.schemas.loader import SchemaLoader, get_schema_loader
from galangal.schemas.models import SchemaResult, SectionValidationResult


class ArtifactSchemaValidator:
    """Validates artifacts against their schemas."""

    def __init__(self, loader: SchemaLoader | None = None):
        """Initialize validator.

        Args:
            loader: Schema loader to use. If None, uses singleton.
        """
        self.loader = loader or get_schema_loader()

    def validate(
        self,
        artifact_name: str,
        content: str,
        task_type: str = "feature",
    ) -> SchemaResult:
        """Validate artifact content against its schema.

        Args:
            artifact_name: Artifact filename (e.g., "SPEC.md").
            content: Artifact content to validate.
            task_type: Task type for section overrides.

        Returns:
            SchemaResult with validation status and any errors/warnings.
        """
        schema = self.loader.get_schema(artifact_name)

        # No schema defined - pass validation
        if schema is None:
            return SchemaResult(valid=True, artifact=artifact_name)

        sections = schema.get_sections_for_task_type(task_type)
        parsed_sections = self._parse_sections(content)

        errors: list[str] = []
        warnings: list[str] = []
        section_results: list[SectionValidationResult] = []

        for name, spec in sections.items():
            # Check if section is present (case-insensitive, normalized)
            normalized_name = self._normalize(name)
            present = normalized_name in parsed_sections

            # Check if section is empty
            empty = False
            if present:
                section_content = parsed_sections[normalized_name]
                empty = self._is_empty(section_content)

            result = SectionValidationResult(
                name=name,
                present=present,
                empty=empty,
            )

            if spec.required:
                if not present:
                    result.error = f"Missing required section: {name}"
                    errors.append(result.error)
                elif empty:
                    result.warning = f"Required section is empty: {name}"
                    warnings.append(result.warning)
            else:
                if present and empty:
                    result.warning = f"Optional section is empty: {name}"
                    warnings.append(result.warning)

            section_results.append(result)

        return SchemaResult(
            valid=len(errors) == 0,
            artifact=artifact_name,
            errors=errors,
            warnings=warnings,
            section_results=section_results,
        )

    def _parse_sections(self, content: str) -> dict[str, str]:
        """Parse markdown into section name -> content mapping.

        Uses the same logic as lineage module for consistency.
        """
        sections: dict[str, str] = {}
        current = "preamble"
        current_lines: list[str] = []

        for line in content.split("\n"):
            if line.startswith("#"):
                # Save previous section
                if current_lines:
                    sections[current] = "\n".join(current_lines)
                # Start new section
                header_text = line.lstrip("#").strip()
                current = self._normalize(header_text)
                current_lines = []
            else:
                current_lines.append(line)

        # Save final section
        if current_lines:
            sections[current] = "\n".join(current_lines)

        return sections

    def _normalize(self, name: str) -> str:
        """Normalize section name for matching."""
        return name.lower().strip().replace(" ", "-")

    def _is_empty(self, content: str) -> bool:
        """Check if section content is effectively empty.

        Empty means only whitespace, comments, or placeholder text.
        """
        # Strip whitespace
        stripped = content.strip()
        if not stripped:
            return True

        # Check for only HTML comments
        import re

        no_comments = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)
        if not no_comments.strip():
            return True

        # Check for only placeholder markers
        placeholders = ["todo", "tbd", "...", "xxx", "fixme"]
        lower = no_comments.lower().strip()
        if lower in placeholders:
            return True

        return False


def validate_artifact(
    artifact_name: str,
    content: str,
    task_type: str = "feature",
) -> SchemaResult:
    """Convenience function to validate an artifact.

    Args:
        artifact_name: Artifact filename (e.g., "SPEC.md").
        content: Artifact content to validate.
        task_type: Task type for section overrides.

    Returns:
        SchemaResult with validation status.
    """
    validator = ArtifactSchemaValidator()
    return validator.validate(artifact_name, content, task_type)
