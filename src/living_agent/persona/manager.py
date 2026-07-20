"""Persona edit, validation, test, deployment, and rollback workflow."""

from __future__ import annotations

from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from living_agent.management.artifacts import ArtifactKind, ArtifactStage
from living_agent.management.service import ManagedArtifactService
from living_agent.persona.schemas import (
    BoundariesSchema,
    GrowthSchema,
    IdentitySchema,
    PersonaProfile,
    SpeechSchema,
    TraitsSchema,
    ValuesSchema,
)

PERSONA_SCHEMAS: dict[str, type[BaseModel]] = {
    "identity.yaml": IdentitySchema,
    "values.yaml": ValuesSchema,
    "traits.yaml": TraitsSchema,
    "speech.yaml": SpeechSchema,
    "boundaries.yaml": BoundariesSchema,
    "growth.yaml": GrowthSchema,
}
_FORBIDDEN_KEYS = {
    "permission",
    "permissions",
    "authority",
    "owner_id",
    "admin_ids",
    "api_key",
    "password",
    "token",
    "root_prompt",
    "system_prompt",
}


class PersonaManager(ManagedArtifactService):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            kind=ArtifactKind.PERSONA,
            allowed_paths=set(PERSONA_SCHEMAS),
            **kwargs,
        )

    def validate(self, artifact_path: str, content: str) -> dict[str, Any]:
        schema = PERSONA_SCHEMAS[artifact_path]
        try:
            payload = yaml.safe_load(content)
            if not isinstance(payload, dict):
                raise ValueError("persona layer must be a YAML object")
            self._reject_forbidden_keys(payload)
            validated = schema.model_validate(payload)
        except (yaml.YAMLError, ValidationError, ValueError) as exc:
            raise ValueError(f"invalid persona layer {artifact_path}: {exc}") from exc
        return {
            "passed": True,
            "schema": schema.__name__,
            "fields": sorted(validated.model_fields_set),
        }

    async def run_tests(self, stage: ArtifactStage) -> dict[str, Any]:
        checked: list[str] = []
        try:
            for artifact_path in sorted(self.allowed_paths):
                content = (
                    stage.content
                    if artifact_path == stage.artifact_path
                    else self._read_file(artifact_path)
                )
                self.validate(artifact_path, content)
                checked.append(artifact_path)
        except ValueError as exc:
            return {"passed": False, "checked_layers": checked, "error": str(exc)}
        return {
            "passed": True,
            "checked_layers": checked,
            "invariants": [
                "ai_disclosure",
                "digital_identity",
                "evidence_backed_claims",
                "no_authority_fields",
            ],
        }

    def restart_required(self, artifact_path: str) -> bool:
        return True

    def identity_statement(self) -> str:
        return self.public_profile().identity.identity_statement

    def public_profile(self) -> PersonaProfile:
        """Load and validate all public persona layers for model context."""

        layers: dict[str, BaseModel] = {}
        for artifact_path, schema in PERSONA_SCHEMAS.items():
            payload = yaml.safe_load(self._read_file(artifact_path))
            if not isinstance(payload, dict):
                raise ValueError(f"persona layer must be a YAML object: {artifact_path}")
            self._reject_forbidden_keys(payload)
            layers[artifact_path.removesuffix(".yaml")] = schema.model_validate(payload)
        return PersonaProfile.model_validate(layers)

    @classmethod
    def _reject_forbidden_keys(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in _FORBIDDEN_KEYS:
                    raise ValueError(f"authority or secret field is forbidden in persona: {key}")
                cls._reject_forbidden_keys(item)
        elif isinstance(value, list):
            for item in value:
                cls._reject_forbidden_keys(item)
