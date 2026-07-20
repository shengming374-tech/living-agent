"""Pure contracts for the host-owned task report capability."""

from pydantic import BaseModel, ConfigDict, Field

TASK_REPORT_CAPABILITY = "task.report"
VERIFIED_RESULTS_PLACEHOLDER = "$VERIFIED_STEP_OUTPUTS"


class TaskReportArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=36, max_length=36)
    content: str = Field(min_length=1, max_length=8000)


def task_report_scope_matches(arguments: BaseModel, resource_scope: str) -> bool:
    return isinstance(arguments, TaskReportArguments) and resource_scope == (
        f"tasks/{arguments.task_id}/report"
    )
