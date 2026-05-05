"""W25.3 — Migration v1 → v2.

Демонстрационная миграция второго поколения. Identity по структуре —
только обновляет ``apiVersion`` и расширяет ``_migrated_from``.

Когда возникнет реальный breaking-change (например, переименование
ключей или изменение формата processor-spec'а), он пойдёт здесь
(или в новой v2 → v3) — framework уже готов.
"""

from __future__ import annotations

from typing import Any


class V1ToV2Migration:
    """v1 → v2: добавляет apiVersion=v2 и обновляет историю миграций."""

    from_version: str = "v1"
    to_version: str = "v2"

    def migrate(self, spec: dict[str, Any]) -> dict[str, Any]:
        result = dict(spec)
        history = list(result.get("_migrated_from", []))
        if not history or history[-1] != "v1":
            history.append("v1")
        result["_migrated_from"] = history
        return result
