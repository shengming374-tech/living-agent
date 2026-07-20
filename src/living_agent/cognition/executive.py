"""Structured Executive Cognition; this module cannot emit user-facing prose."""

from living_agent.execution.contracts import (
    CALCULATOR_CAPABILITY,
    CALCULATOR_PLUGIN_ID,
    CALCULATOR_SCOPE,
    ExecutiveProposal,
    extract_calculation_expression,
)
from living_agent.models.capabilities import CapabilityRequest
from living_agent.models.events import AuthorityLevel, TrustedEvent
from living_agent.models.tasks import TaskContract


class ExecutiveCognition:
    def propose(self, event: TrustedEvent) -> ExecutiveProposal | None:
        expression = extract_calculation_expression(event.content)
        if expression is None or event.authority_level is AuthorityLevel.ANONYMOUS:
            return None
        requester_id = event.source_identity
        if requester_id is None:
            return None
        task = TaskContract(
            requester_id=requester_id,
            goal=f"Evaluate the supplied arithmetic expression: {expression}",
            constraints=[
                "Use only the isolated calculator plugin",
                "Do not access files, network, memory, or environment secrets",
            ],
            allowed_capabilities=[CALCULATOR_CAPABILITY],
            forbidden_operations=[
                "filesystem.read",
                "filesystem.write",
                "network.send",
                "message.send",
            ],
            success_criteria=[
                "Return a finite numeric value",
                "Host independently verifies the arithmetic result",
            ],
            confirmation_requirements=[],
        )
        request = CapabilityRequest(
            actor_id=requester_id,
            capability=CALCULATOR_CAPABILITY,
            operation="execute",
            resource_scope=CALCULATOR_SCOPE,
            arguments={"expression": expression},
            source_event_ids=[event.event_id],
            taint_labels=set(event.taint_labels),
            reason="Execute the explicitly requested bounded arithmetic task.",
            conversation_id=event.conversation_id,
        )
        return ExecutiveProposal(
            task=task,
            capability_request=request,
            plugin_id=CALCULATOR_PLUGIN_ID,
            plugin_operation="calculate",
        )
