"""Pydantic schemas for the six non-authority persona layers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentitySchema(StrictSchema):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["digital_persona"]
    identity_statement: str = Field(min_length=20, max_length=1000)
    ai_disclosure: Literal[True]

    @field_validator("identity_statement")
    @classmethod
    def require_digital_identity(cls, value: str) -> str:
        if "digital" not in value.lower():
            raise ValueError("identity statement must identify the persona as digital")
        return value


class ValuesSchema(StrictSchema):
    principles: list[str] = Field(min_length=1, max_length=20)
    priorities: list[str] = Field(min_length=1, max_length=20)


class TraitsSchema(StrictSchema):
    curiosity: float = Field(ge=0.0, le=1.0)
    warmth: float = Field(ge=0.0, le=1.0)
    assertiveness: float = Field(ge=0.0, le=1.0)
    playfulness: float = Field(ge=0.0, le=1.0)


class SpeechSchema(StrictSchema):
    languages: list[str] = Field(min_length=1, max_length=10)
    style: list[str] = Field(min_length=1, max_length=20)
    avoid: list[str] = Field(min_length=1, max_length=30)


class BoundariesSchema(StrictSchema):
    never_claim_biological_body: Literal[True]
    require_evidence_for_memory_claims: Literal[True]
    require_evidence_for_prior_thought_claims: Literal[True]
    social_boundaries: list[str] = Field(min_length=1, max_length=30)


class GrowthSchema(StrictSchema):
    mutable_traits: list[str] = Field(max_length=20)
    immutable_commitments: list[str] = Field(min_length=1, max_length=20)
    owner_review_required: Literal[True]


class PersonaProfile(StrictSchema):
    """The complete public persona profile, excluding authority and secrets."""

    identity: IdentitySchema
    values: ValuesSchema
    traits: TraitsSchema
    speech: SpeechSchema
    boundaries: BoundariesSchema
    growth: GrowthSchema
