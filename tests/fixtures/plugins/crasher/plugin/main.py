import os
from typing import Any


def invoke(params: dict[str, Any]) -> dict[str, Any]:
    os._exit(17)
