from typing import Any


def invoke(params: dict[str, Any]) -> dict[str, Any]:
    print("x" * 100_000)
    return {"ok": True}
