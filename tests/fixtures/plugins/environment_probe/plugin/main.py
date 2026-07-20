import os
from typing import Any


def invoke(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "secret_visible": "LIVING_AGENT_SECRET_DO_NOT_SHARE" in os.environ,
        "plugin_id": os.environ.get("LIVING_AGENT_PLUGIN_ID"),
    }
