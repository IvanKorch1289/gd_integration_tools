"""W25.3 — Migration v0 → v1.

Демонстрационная миграция первого поколения.

Изменения:

* добавляется поле ``apiVersion: v1`` (если отсутствовало);
* добавляется метаданный блок ``_migrated_from`` для трассировки
  истории изменений (best-effort, не обязательная часть spec'а).

Никакой структурной правки не делается — это **identity-миграция**,
демонстрирующая каркас. Реальные breaking changes придут с будущими
v2/v3, когда YAML-формат поменяется.
"""

from __future__ import annotations

from typing import Any


class V0ToV1Migration:
    """v0 → v1: добавляет apiVersion и сервисный маркер миграции."""

    from_version: str = "v0"
    to_version: str = "v1"

    def migrate(self, spec: dict[str, Any]) -> dict[str, Any]:
        result = dict(spec)
        history = list(result.get("_migrated_from", []))
        history.append("v0")
        result["_migrated_from"] = history
        return result
