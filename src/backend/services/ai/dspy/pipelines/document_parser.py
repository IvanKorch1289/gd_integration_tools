"""document_parser DSPy-pipeline (K4 S6 W2).

Извлекает структурные поля (passport_number, full_name, dob) из текста
банковского документа (паспорт/доверенность/выписка).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_PASSPORT_RE = re.compile(r"\b(\d{4})\s?(\d{6})\b")
_DOB_RE = re.compile(r"\b\d{2}[./]\d{2}[./]\d{4}\b")


@dataclass(frozen=True, slots=True)
class _DocumentParserPipeline:
    name: str = "document_parser"
    description: str = "Извлечение fields из банковских документов (passport/dob/fullname)"

    def forward(self, example: dict[str, Any]) -> str:
        text = str(example.get("input") or example.get("context") or "")
        passport = ""
        dob = ""
        full_name = ""

        if m := _PASSPORT_RE.search(text):
            passport = f"{m.group(1)} {m.group(2)}"

        if m := _DOB_RE.search(text):
            dob = m.group(0)

        # Простая эвристика: ищем 3 заглавных слова подряд.
        words = text.split()
        for i in range(len(words) - 2):
            trio = words[i : i + 3]
            if all(w and w[0].isupper() and any(c.isalpha() for c in w) for w in trio):
                full_name = " ".join(trio).strip(",.")
                break

        return json.dumps(
            {"passport": passport, "dob": dob, "full_name": full_name},
            ensure_ascii=False,
        )

    def metric(self, example: dict[str, Any], output: str) -> float:
        try:
            parsed = json.loads(output)
        except Exception:  # noqa: BLE001
            return 0.0
        expected = example.get("expected") or {}
        if isinstance(expected, str):
            try:
                expected = json.loads(expected)
            except Exception:  # noqa: BLE001
                expected = {}
        if not isinstance(expected, dict):
            return 0.0

        hit = 0
        total = 0
        for key in ("passport", "dob", "full_name"):
            if expected.get(key):
                total += 1
                if str(parsed.get(key, "")).strip() == str(expected.get(key, "")).strip():
                    hit += 1
        if total == 0:
            return 1.0
        return hit / total


document_parser_pipeline = _DocumentParserPipeline()
__all__ = ("document_parser_pipeline",)
