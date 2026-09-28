from __future__ import annotations

import io
from typing import Any

SAFE_BUILTINS: dict[str, Any] = {
    name: __builtins__[name]  # type: ignore[index]
    for name in [
        "abs",
        "bool",
        "dict",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "print",
        "range",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
    ]
}


def execute_code(code: str, timeout_seconds: int = 2) -> dict[str, Any]:
    stdout = io.StringIO()
    namespace: dict[str, Any] = {
        "__builtins__": SAFE_BUILTINS,
        "result": None,
    }

    try:
        compiled = compile(code, "<agent_code>", "exec")
        exec(compiled, namespace, namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stdout": stdout.getvalue(), "error": str(exc), "result": namespace.get("result")}

    return {"ok": True, "stdout": stdout.getvalue(), "error": None, "result": namespace.get("result")}
