"""
Artifact schema validation.
"""

from __future__ import annotations

import re

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
            # Check if section is present (case-insensitive, normalized, tolerant
            # of numbering / decoration / extra words in the header).
            normalized_name = self._normalize(name)
            matched_key = next(
                (key for key in parsed_sections if self._section_matches(normalized_name, key)),
                None,
            )
            present = matched_key is not None

            # Check if section is empty
            empty = False
            if present:
                empty = self._is_empty(parsed_sections[matched_key])

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

        Recognizes both ``#`` headers and standalone bold-label lines
        (``**Acceptance Criteria**``) as section boundaries, since models
        frequently use the latter.
        """
        sections: dict[str, str] = {}
        current = "preamble"
        current_lines: list[str] = []

        for line in content.split("\n"):
            header_text = self._header_text(line)
            if header_text is not None:
                # Save previous section
                if current_lines:
                    sections[current] = "\n".join(current_lines)
                # Start new section
                current = self._normalize(header_text)
                current_lines = []
            else:
                current_lines.append(line)

        # Save final section
        if current_lines:
            sections[current] = "\n".join(current_lines)

        return sections

    def _header_text(self, line: str) -> str | None:
        """Return the header text if the line is a section header, else None.

        A header is a ``#``-prefixed line, or a standalone fully-bold line.
        """
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        # Standalone bold label, e.g. "**Acceptance Criteria**" / "__Risks__"
        for marker in ("**", "__"):
            if (
                stripped.startswith(marker)
                and stripped.endswith(marker)
                and len(stripped) > 2 * len(marker)
                and marker not in stripped[len(marker) : -len(marker)]
            ):
                return stripped[len(marker) : -len(marker)].strip()
        return None

    def _normalize(self, name: str) -> str:
        """Normalize a section name for matching (shared with the lineage tracker)."""
        from galangal.core.utils import normalize_section_name

        return normalize_section_name(name)

    def _section_matches(self, target: str, key: str) -> bool:
        """Whether a parsed header ``key`` satisfies required section ``target``.

        Matches if equal, or if the target's hyphen tokens appear as a contiguous
        run within the key's tokens (so ``acceptance-criteria`` matches
        ``acceptance-criteria-v2`` and a numbering-stripped ``acceptance-criteria``).
        """
        if not target:
            return False
        if target == key:
            return True
        t = target.split("-")
        k = key.split("-")
        n = len(t)
        return any(k[i : i + n] == t for i in range(len(k) - n + 1))

    def _is_empty(self, content: str) -> bool:
        """Check if section content is effectively empty.

        Empty means only whitespace, comments, or placeholder text.
        """
        # Strip whitespace
        stripped = content.strip()
        if not stripped:
            return True

        # Check for only HTML comments
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
