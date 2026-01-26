"""
Schema loading with defaults and project overrides.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from galangal.schemas.models import ArtifactSchema

# Default schemas embedded in code
DEFAULT_SCHEMAS: dict[str, dict[str, Any]] = {
    "SPEC.md": {
        "artifact": "SPEC.md",
        "produced_by": "PM",
        "sections": {
            "overview": {
                "required": True,
                "description": "Brief summary of what this task accomplishes",
            },
            "requirements": {
                "required": True,
                "description": "Functional requirements as clear, testable statements",
            },
            "acceptance-criteria": {
                "required": True,
                "description": "Conditions that must be met for the task to be complete",
            },
            "constraints": {
                "required": False,
                "description": "Technical or business constraints",
            },
            "out-of-scope": {
                "required": False,
                "description": "What is explicitly not included in this task",
            },
        },
        "task_type_overrides": {
            "bug_fix": {
                "sections": {
                    "requirements": {"required": False},
                    "reproduction-steps": {
                        "required": True,
                        "description": "Steps to reproduce the bug",
                    },
                    "expected-behavior": {
                        "required": True,
                        "description": "What should happen",
                    },
                    "actual-behavior": {
                        "required": True,
                        "description": "What currently happens",
                    },
                }
            },
            "hotfix": {
                "sections": {
                    "requirements": {"required": False},
                    "constraints": {"required": False},
                }
            },
            "docs": {
                "sections": {
                    "requirements": {"required": False},
                    "acceptance-criteria": {"required": False},
                    "content-outline": {
                        "required": True,
                        "description": "Outline of documentation to create/update",
                    },
                }
            },
        },
    },
    "DESIGN.md": {
        "artifact": "DESIGN.md",
        "produced_by": "DESIGN",
        "sections": {
            "overview": {
                "required": True,
                "description": "High-level design approach",
            },
            "architecture": {
                "required": True,
                "description": "System/component architecture decisions",
            },
            "components": {
                "required": True,
                "description": "Key components and their responsibilities",
            },
            "data-model": {
                "required": False,
                "description": "Data structures and models",
            },
            "api-design": {
                "required": False,
                "description": "API contracts and interfaces",
            },
            "alternatives-considered": {
                "required": False,
                "description": "Other approaches that were evaluated",
            },
        },
        "task_type_overrides": {
            "bug_fix": {
                "sections": {
                    "architecture": {"required": False},
                    "components": {"required": False},
                    "root-cause": {
                        "required": True,
                        "description": "Analysis of why the bug occurs",
                    },
                    "fix-approach": {
                        "required": True,
                        "description": "How the bug will be fixed",
                    },
                }
            },
            "refactor": {
                "sections": {
                    "current-state": {
                        "required": True,
                        "description": "Current code structure and issues",
                    },
                    "target-state": {
                        "required": True,
                        "description": "Desired code structure after refactoring",
                    },
                }
            },
        },
    },
    "PLAN.md": {
        "artifact": "PLAN.md",
        "produced_by": "DESIGN",
        "sections": {
            "overview": {
                "required": True,
                "description": "Summary of implementation approach",
            },
            "implementation-steps": {
                "required": True,
                "description": "Ordered list of implementation steps",
            },
            "file-changes": {
                "required": True,
                "description": "Files to create, modify, or delete",
            },
            "testing-strategy": {
                "required": False,
                "description": "How the implementation will be tested",
            },
            "risks": {
                "required": False,
                "description": "Potential risks and mitigations",
            },
        },
        "task_type_overrides": {
            "hotfix": {
                "sections": {
                    "testing-strategy": {"required": True},
                    "risks": {"required": True},
                }
            },
        },
    },
}

# Singleton loader instance
_loader: SchemaLoader | None = None


class SchemaLoader:
    """Loads artifact schemas from defaults and project overrides."""

    def __init__(self, project_root: Path | None = None):
        """Initialize the schema loader.

        Args:
            project_root: Project root directory. If None, uses config loader.
        """
        self._project_root = project_root
        self._cache: dict[str, ArtifactSchema] = {}

    @property
    def project_root(self) -> Path:
        """Get project root, lazily loaded."""
        if self._project_root is None:
            from galangal.config.loader import get_project_root

            self._project_root = get_project_root()
        return self._project_root

    @property
    def schemas_dir(self) -> Path:
        """Get project schemas directory."""
        return self.project_root / ".galangal" / "schemas"

    def get_schema(self, artifact_name: str) -> ArtifactSchema | None:
        """Get schema for an artifact, with caching.

        Args:
            artifact_name: Artifact filename (e.g., "SPEC.md").

        Returns:
            ArtifactSchema if found, None otherwise.
        """
        if artifact_name in self._cache:
            return self._cache[artifact_name]

        schema = self._load_schema(artifact_name)
        if schema:
            self._cache[artifact_name] = schema
        return schema

    def _load_schema(self, artifact_name: str) -> ArtifactSchema | None:
        """Load schema from project override or defaults.

        Project overrides take precedence over defaults.
        """
        # Check for project override
        override_path = self.schemas_dir / f"{artifact_name}.yaml"
        if override_path.exists():
            try:
                with open(override_path) as f:
                    data = yaml.safe_load(f)
                if data:
                    return ArtifactSchema.from_dict(data)
            except Exception:
                pass  # Fall back to default

        # Use default schema
        if artifact_name in DEFAULT_SCHEMAS:
            return ArtifactSchema.from_dict(DEFAULT_SCHEMAS[artifact_name])

        return None

    def list_schemas(self) -> list[str]:
        """List all available schema names."""
        names = set(DEFAULT_SCHEMAS.keys())

        if self.schemas_dir.exists():
            for path in self.schemas_dir.glob("*.yaml"):
                # Extract artifact name from filename
                artifact_name = path.stem
                if not artifact_name.endswith(".md"):
                    artifact_name += ".md"
                names.add(artifact_name)

        return sorted(names)

    def export_schema(self, artifact_name: str, output_path: Path) -> bool:
        """Export a schema to YAML file.

        Args:
            artifact_name: Artifact to export schema for.
            output_path: Where to write the YAML file.

        Returns:
            True if exported successfully.
        """
        schema = self.get_schema(artifact_name)
        if not schema:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            yaml.dump(schema.to_dict(), f, default_flow_style=False, sort_keys=False)
        return True

    def generate_template(self, artifact_name: str, task_type: str = "feature") -> str:
        """Generate a markdown template from schema.

        Args:
            artifact_name: Artifact to generate template for.
            task_type: Task type for section overrides.

        Returns:
            Markdown template string.
        """
        schema = self.get_schema(artifact_name)
        if not schema:
            return f"# {artifact_name}\n\nNo schema defined.\n"

        sections = schema.get_sections_for_task_type(task_type)
        lines = []

        for name, spec in sections.items():
            # Convert section name to title case
            title = name.replace("-", " ").title()
            lines.append(f"# {title}")
            lines.append("")

            # Add description as comment
            if spec.description:
                required = "(required)" if spec.required else "(optional)"
                lines.append(f"<!-- {spec.description} {required} -->")
                lines.append("")

            lines.append("")

        return "\n".join(lines)

    def clear_cache(self) -> None:
        """Clear the schema cache."""
        self._cache.clear()


def get_schema_loader() -> SchemaLoader:
    """Get the singleton schema loader instance."""
    global _loader
    if _loader is None:
        _loader = SchemaLoader()
    return _loader


def reset_schema_loader() -> None:
    """Reset the singleton loader (for testing)."""
    global _loader
    _loader = None
