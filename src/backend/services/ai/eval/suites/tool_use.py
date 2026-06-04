"""tool_use suite — корректность вызова MCP tools (K4 S6 W1).

Каждый sample описывает: какой MCP tool должен быть вызван, с какими
обязательными аргументами. Output моделирует JSON-структуру function-call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _ToolUse:
    name: str = "tool_use"
    description: str = "Корректность вызова MCP tools: имя + arguments"

    def build_dataset(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "tool-1",
                "task": "Получить кредитную историю клиента",
                "expected_tool": "credit.history.fetch",
                "required_args": ["client_id"],
                "expected": json.dumps(
                    {"tool": "credit.history.fetch", "arguments": {"client_id": "X"}}
                ),
            },
            {
                "id": "tool-2",
                "task": "Создать запрос на скоринг",
                "expected_tool": "credit.scoring.create",
                "required_args": ["application_id", "tenant_id"],
                "expected": json.dumps(
                    {
                        "tool": "credit.scoring.create",
                        "arguments": {"application_id": "A1", "tenant_id": "t1"},
                    }
                ),
            },
            {
                "id": "tool-3",
                "task": "Получить документ из RAG",
                "expected_tool": "rag.document.get",
                "required_args": ["doc_id"],
                "expected": json.dumps(
                    {"tool": "rag.document.get", "arguments": {"doc_id": "d-1"}}
                ),
            },
        ]

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        try:
            parsed = json.loads(output)
        except Exception as _:
            return {"tool_name_correct": 0.0, "args_coverage": 0.0}
        tool = parsed.get("tool")
        args = parsed.get("arguments") or {}
        name_ok = 1.0 if tool == sample.get("expected_tool") else 0.0
        required = sample.get("required_args") or []
        if not required:
            coverage = 1.0
        else:
            hit = sum(1 for a in required if a in args)
            coverage = hit / len(required)
        return {"tool_name_correct": name_ok, "args_coverage": float(coverage)}


tool_use_suite = _ToolUse()
__all__ = ("tool_use_suite",)
