import time
from typing import Any


def invoke(params: dict[str, Any]) -> dict[str, Any]:
    time.sleep(2)
    return {"unexpected": "late result"}
