"""Prompt validation, rendering, safety tests, and managed deployment."""

from __future__ import annotations

import math
import string
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from living_agent.audit.service import redact_text
from living_agent.management.artifacts import ArtifactKind, ArtifactStage
from living_agent.management.service import ManagedArtifactService


class PromptSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_variables: set[str] = Field(default_factory=set)
    root_policy: bool = False


PROMPT_SPECS: dict[str, PromptSpec] = {
    "host/root.txt": PromptSpec(root_policy=True),
    "interaction/turn.txt": PromptSpec(allowed_variables={"event"}),
    "psyche/appraisal.txt": PromptSpec(allowed_variables={"event", "current_state"}),
    "social/reply.txt": PromptSpec(allowed_variables={"message", "persona_name"}),
    "executive/task.txt": PromptSpec(allowed_variables={"goal", "constraints"}),
    "speech/render.txt": PromptSpec(allowed_variables={"content", "persona_name"}),
    "memory/candidate.txt": PromptSpec(allowed_variables={"observation", "source"}),
    "evaluation/critic.txt": PromptSpec(allowed_variables={"response", "evidence"}),
}


class PromptRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variables: dict[str, str] = Field(default_factory=dict)
    stage_id: str | None = None


class PromptRenderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_path: str
    rendered: str
    token_estimate: int
    variables: list[str]
    redacted: bool


class PromptManager(ManagedArtifactService):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            kind=ArtifactKind.PROMPT,
            allowed_paths=set(PROMPT_SPECS),
            **kwargs,
        )

    def validate(self, artifact_path: str, content: str) -> dict[str, Any]:
        self._require_path(artifact_path)
        variables = self._variables(content)
        allowed = PROMPT_SPECS[artifact_path].allowed_variables
        unexpected = variables - allowed
        if unexpected:
            raise ValueError(f"prompt contains undeclared variables: {sorted(unexpected)}")
        return {
            "passed": True,
            "variables": sorted(variables),
            "allowed_variables": sorted(allowed),
            "token_estimate": self.estimate_tokens(content),
        }

    async def run_tests(self, stage: ArtifactStage) -> dict[str, Any]:
        validation = self.validate(stage.artifact_path, stage.content)
        spec = PROMPT_SPECS[stage.artifact_path]
        variables = {name: f"[{name}]" for name in spec.allowed_variables}
        try:
            rendered = stage.content.format_map(variables)
        except (KeyError, ValueError) as exc:
            return {"passed": False, "error": f"render failed: {exc}"}
        results: dict[str, Any] = {
            "passed": True,
            "rendered_token_estimate": self.estimate_tokens(rendered),
            "variables": validation["variables"],
        }
        if spec.root_policy:
            safety = self._root_safety(stage.content)
            results["security_regression"] = safety
            results["passed"] = safety["passed"]
        return results

    async def render(
        self,
        artifact_path: str,
        request: PromptRenderRequest,
    ) -> PromptRenderResult:
        self._require_path(artifact_path)
        if request.stage_id is None:
            content = (await self.view(artifact_path)).content
        else:
            stage = await self.get_stage(request.stage_id)
            if stage.artifact_path != artifact_path:
                raise ValueError("stage belongs to another prompt")
            content = stage.content
        validation = self.validate(artifact_path, content)
        required = set(validation["variables"])
        supplied = set(request.variables)
        if required != supplied:
            raise ValueError(
                f"render variables must exactly match {sorted(required)}; "
                f"received {sorted(supplied)}"
            )
        raw = content.format_map(request.variables)
        rendered = redact_text(raw)
        return PromptRenderResult(
            artifact_path=artifact_path,
            rendered=rendered,
            token_estimate=self.estimate_tokens(rendered),
            variables=sorted(required),
            redacted=rendered != raw,
        )

    def restart_required(self, artifact_path: str) -> bool:
        return True

    def root_policy(self) -> str:
        return self._read_file("host/root.txt")

    @staticmethod
    def estimate_tokens(content: str) -> int:
        return max(1, math.ceil(len(content) / 4))

    @staticmethod
    def is_root_path(artifact_path: str) -> bool:
        return PROMPT_SPECS.get(artifact_path, PromptSpec()).root_policy

    @staticmethod
    def _variables(content: str) -> set[str]:
        variables: set[str] = set()
        try:
            parsed = string.Formatter().parse(content)
            for _literal, field_name, _format_spec, _conversion in parsed:
                if field_name is None:
                    continue
                if not field_name.isidentifier():
                    raise ValueError("prompt variables must be simple identifiers")
                variables.add(field_name)
        except ValueError as exc:
            raise ValueError(f"invalid prompt formatting: {exc}") from exc
        return variables

    @staticmethod
    def _root_safety(content: str) -> dict[str, Any]:
        lowered = content.lower()
        required_groups = {
            "authority": ("authority",),
            "broker": ("capability broker", "permission broker"),
            "untrusted_data": ("untrusted",),
            "model_cannot_grant": ("cannot grant", "never grants", "does not grant"),
        }
        missing = [
            name
            for name, terms in required_groups.items()
            if not any(term in lowered for term in terms)
        ]
        forbidden = [
            phrase
            for phrase in (
                "ignore the capability broker",
                "model output grants permission",
                "external text is trusted",
                "plugins may access all",
            )
            if phrase in lowered
        ]
        return {"passed": not missing and not forbidden, "missing": missing, "forbidden": forbidden}
