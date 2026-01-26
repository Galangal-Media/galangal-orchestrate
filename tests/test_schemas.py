"""Tests for artifact schema validation."""

from galangal.schemas import (
    ArtifactSchema,
    ArtifactSchemaValidator,
    SchemaLoader,
    SchemaResult,
    SectionSpec,
)
from galangal.schemas.loader import DEFAULT_SCHEMAS, reset_schema_loader


class TestSectionSpec:
    """Tests for SectionSpec model."""

    def test_from_dict_bool_shorthand(self):
        """Test creating SectionSpec from boolean shorthand."""
        spec = SectionSpec.from_dict("overview", True)
        assert spec.name == "overview"
        assert spec.required is True

        spec = SectionSpec.from_dict("optional", False)
        assert spec.name == "optional"
        assert spec.required is False

    def test_from_dict_full_spec(self):
        """Test creating SectionSpec from full dictionary."""
        spec = SectionSpec.from_dict(
            "requirements",
            {"required": True, "description": "List of requirements"},
        )
        assert spec.name == "requirements"
        assert spec.required is True
        assert spec.description == "List of requirements"

    def test_from_dict_defaults(self):
        """Test SectionSpec defaults."""
        spec = SectionSpec.from_dict("minimal", {})
        assert spec.name == "minimal"
        assert spec.required is True  # Default
        assert spec.description == ""  # Default


class TestArtifactSchema:
    """Tests for ArtifactSchema model."""

    def test_from_dict_basic(self):
        """Test creating schema from dictionary."""
        schema = ArtifactSchema.from_dict({
            "artifact": "TEST.md",
            "produced_by": "TEST",
            "sections": {
                "overview": True,
                "test-cases": {"required": True},
                "notes": {"required": False},
            },
        })

        assert schema.artifact == "TEST.md"
        assert schema.produced_by == "TEST"
        assert len(schema.sections) == 3
        assert schema.sections["overview"].required is True
        assert schema.sections["test-cases"].required is True
        assert schema.sections["notes"].required is False

    def test_get_sections_for_task_type_no_override(self):
        """Test getting sections without task type override."""
        schema = ArtifactSchema.from_dict({
            "artifact": "SPEC.md",
            "sections": {
                "requirements": True,
                "constraints": False,
            },
        })

        sections = schema.get_sections_for_task_type("feature")
        assert len(sections) == 2
        assert sections["requirements"].required is True

    def test_get_sections_for_task_type_with_override(self):
        """Test getting sections with task type override."""
        schema = ArtifactSchema.from_dict({
            "artifact": "SPEC.md",
            "sections": {
                "requirements": True,
                "constraints": False,
            },
            "task_type_overrides": {
                "bug_fix": {
                    "sections": {
                        "requirements": {"required": False},
                        "reproduction-steps": {"required": True},
                    }
                }
            },
        })

        # Feature gets base sections
        feature_sections = schema.get_sections_for_task_type("feature")
        assert feature_sections["requirements"].required is True
        assert "reproduction-steps" not in feature_sections

        # Bug fix gets overridden sections
        bugfix_sections = schema.get_sections_for_task_type("bug_fix")
        assert bugfix_sections["requirements"].required is False
        assert bugfix_sections["reproduction-steps"].required is True

    def test_to_dict(self):
        """Test schema serialization."""
        schema = ArtifactSchema.from_dict({
            "artifact": "TEST.md",
            "produced_by": "TEST",
            "sections": {"overview": True},
        })

        d = schema.to_dict()
        assert d["artifact"] == "TEST.md"
        assert d["produced_by"] == "TEST"
        assert "overview" in d["sections"]


class TestSchemaResult:
    """Tests for SchemaResult model."""

    def test_format_feedback_with_errors(self):
        """Test feedback formatting with errors."""
        result = SchemaResult(
            valid=False,
            artifact="SPEC.md",
            errors=["Missing required section: requirements"],
            warnings=["Optional section is empty: constraints"],
        )

        feedback = result.format_feedback()
        assert "SPEC.md schema validation failed" in feedback
        assert "Missing required section: requirements" in feedback
        assert "Optional section is empty: constraints" in feedback
        assert "Please revise" in feedback

    def test_format_feedback_valid(self):
        """Test feedback formatting for valid result."""
        result = SchemaResult(valid=True, artifact="SPEC.md")
        feedback = result.format_feedback()
        assert feedback == ""  # No feedback for valid results


class TestSchemaLoader:
    """Tests for SchemaLoader."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_schema_loader()

    def test_get_default_schema(self):
        """Test loading default schema."""
        loader = SchemaLoader()
        schema = loader.get_schema("SPEC.md")

        assert schema is not None
        assert schema.artifact == "SPEC.md"
        assert "overview" in schema.sections
        assert "requirements" in schema.sections

    def test_get_nonexistent_schema(self):
        """Test loading non-existent schema returns None."""
        loader = SchemaLoader()
        schema = loader.get_schema("NONEXISTENT.md")
        assert schema is None

    def test_list_schemas(self):
        """Test listing available schemas."""
        loader = SchemaLoader()
        schemas = loader.list_schemas()

        assert "SPEC.md" in schemas
        assert "DESIGN.md" in schemas
        assert "PLAN.md" in schemas

    def test_generate_template(self):
        """Test generating markdown template from schema."""
        loader = SchemaLoader()
        template = loader.generate_template("SPEC.md", "feature")

        assert "# Overview" in template
        assert "# Requirements" in template
        assert "# Acceptance Criteria" in template
        assert "(required)" in template

    def test_generate_template_task_type_override(self):
        """Test template generation with task type override."""
        loader = SchemaLoader()
        template = loader.generate_template("SPEC.md", "bug_fix")

        # Bug fix should have reproduction steps
        assert "# Reproduction" in template or "# Expected" in template

    def test_caching(self):
        """Test schema caching."""
        loader = SchemaLoader()

        schema1 = loader.get_schema("SPEC.md")
        schema2 = loader.get_schema("SPEC.md")

        assert schema1 is schema2  # Same object from cache

    def test_clear_cache(self):
        """Test cache clearing."""
        loader = SchemaLoader()
        loader.get_schema("SPEC.md")
        loader.clear_cache()

        # After clear, should reload
        assert "SPEC.md" not in loader._cache


class TestArtifactSchemaValidator:
    """Tests for ArtifactSchemaValidator."""

    def test_validate_valid_artifact(self):
        """Test validating artifact with all required sections."""
        validator = ArtifactSchemaValidator()

        content = """# Overview

This is a brief overview of the task.

# Requirements

- Requirement 1
- Requirement 2

# Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2
"""
        result = validator.validate("SPEC.md", content, "feature")

        assert result.valid is True
        assert len(result.errors) == 0

    def test_validate_missing_required_section(self):
        """Test validating artifact missing required section."""
        validator = ArtifactSchemaValidator()

        content = """# Overview

This is a brief overview.

# Requirements

- Requirement 1
"""
        # Missing acceptance-criteria
        result = validator.validate("SPEC.md", content, "feature")

        assert result.valid is False
        assert any("acceptance-criteria" in e.lower() for e in result.errors)

    def test_validate_empty_required_section(self):
        """Test validating artifact with empty required section."""
        validator = ArtifactSchemaValidator()

        content = """# Overview

This is a brief overview.

# Requirements

<!-- TODO -->

# Acceptance Criteria

- [ ] Criterion 1
"""
        result = validator.validate("SPEC.md", content, "feature")

        # Empty required section should be a warning, not error
        assert any("empty" in w.lower() for w in result.warnings)

    def test_validate_no_schema(self):
        """Test validating artifact with no schema passes."""
        validator = ArtifactSchemaValidator()

        result = validator.validate("UNKNOWN.md", "any content", "feature")

        assert result.valid is True

    def test_validate_case_insensitive_sections(self):
        """Test section matching is case-insensitive."""
        validator = ArtifactSchemaValidator()

        content = """# OVERVIEW

This is an overview.

# REQUIREMENTS

- Req 1

# acceptance-criteria

- [ ] Criterion
"""
        result = validator.validate("SPEC.md", content, "feature")

        # Should find all sections despite case differences
        assert result.valid is True

    def test_validate_with_task_type_override(self):
        """Test validation with task type specific requirements."""
        validator = ArtifactSchemaValidator()

        # Bug fix content - doesn't need regular requirements
        content = """# Overview

Bug fix overview.

# Reproduction Steps

1. Do X
2. See error

# Expected Behavior

Should do Y.

# Actual Behavior

Does Z instead.

# Acceptance Criteria

- [ ] Bug is fixed
"""
        result = validator.validate("SPEC.md", content, "bug_fix")

        # Should pass with bug_fix sections
        assert result.valid is True


class TestDefaultSchemas:
    """Tests for default schema definitions."""

    def test_spec_schema_has_required_sections(self):
        """Test SPEC.md schema has expected sections."""
        schema_data = DEFAULT_SCHEMAS.get("SPEC.md")
        assert schema_data is not None

        sections = schema_data.get("sections", {})
        assert "overview" in sections
        assert "requirements" in sections
        assert "acceptance-criteria" in sections

    def test_design_schema_has_required_sections(self):
        """Test DESIGN.md schema has expected sections."""
        schema_data = DEFAULT_SCHEMAS.get("DESIGN.md")
        assert schema_data is not None

        sections = schema_data.get("sections", {})
        assert "overview" in sections
        assert "architecture" in sections

    def test_plan_schema_has_required_sections(self):
        """Test PLAN.md schema has expected sections."""
        schema_data = DEFAULT_SCHEMAS.get("PLAN.md")
        assert schema_data is not None

        sections = schema_data.get("sections", {})
        assert "implementation-steps" in sections
        assert "file-changes" in sections

    def test_bug_fix_overrides_exist(self):
        """Test bug_fix task type overrides are defined."""
        spec_schema = DEFAULT_SCHEMAS.get("SPEC.md", {})
        overrides = spec_schema.get("task_type_overrides", {})

        assert "bug_fix" in overrides
        bug_fix = overrides["bug_fix"]
        sections = bug_fix.get("sections", {})

        assert "reproduction-steps" in sections
        assert "expected-behavior" in sections


class TestSchemaValidationIntegration:
    """Integration tests for schema validation."""

    def test_validate_real_spec_artifact(self):
        """Test validating a realistic SPEC.md artifact."""
        validator = ArtifactSchemaValidator()

        content = """# Overview

Implement user authentication with JWT tokens for the API.

# Requirements

- Users can register with email and password
- Users can log in and receive a JWT token
- Protected endpoints require valid JWT
- Tokens expire after 24 hours

# Acceptance Criteria

- [ ] POST /auth/register creates new user
- [ ] POST /auth/login returns JWT token
- [ ] GET /protected returns 401 without token
- [ ] GET /protected returns 200 with valid token

# Constraints

- Must use existing User model
- No third-party auth providers for v1

# Out of Scope

- Password reset flow
- Social login
"""
        result = validator.validate("SPEC.md", content, "feature")

        assert result.valid is True
        assert len(result.errors) == 0

    def test_validate_minimal_hotfix_spec(self):
        """Test validating minimal hotfix SPEC.md."""
        validator = ArtifactSchemaValidator()

        content = """# Overview

Fix crash when user email is null.

# Acceptance Criteria

- [ ] No crash on null email
"""
        result = validator.validate("SPEC.md", content, "hotfix")

        # Hotfix has relaxed requirements
        assert result.valid is True
