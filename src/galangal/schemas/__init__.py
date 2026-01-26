"""
Artifact schema definitions and validation.

Provides schema-based validation for stage output artifacts, ensuring
required sections are present and content meets minimum requirements.
"""

from galangal.schemas.loader import SchemaLoader, get_schema_loader
from galangal.schemas.models import ArtifactSchema, SchemaResult, SectionSpec
from galangal.schemas.validator import ArtifactSchemaValidator

__all__ = [
    "ArtifactSchema",
    "ArtifactSchemaValidator",
    "SchemaLoader",
    "SchemaResult",
    "SectionSpec",
    "get_schema_loader",
]
