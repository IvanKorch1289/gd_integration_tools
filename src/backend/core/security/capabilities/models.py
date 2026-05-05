"""ADR-044 — pydantic-модель ``CapabilityRef`` + v0-каталог.

`CapabilityRef` живёт в ``core/`` (а не в ``services/plugins/``),
потому что она используется и Plugin-, и Route-манифестами и
импортируется runtime-gate'ом, который тоже в ``core/``. Layer policy:
``services/`` импортирует ``core/``, не наоборот.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ("CAPABILITY_NAME_PATTERN", "CapabilityRef", "DEFAULT_CAPABILITY_CATALOG")

CAPABILITY_NAME_PATTERN: Final[str] = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
"""Грамматика имени capability: ``<resource>.<verb>``."""

_CAPABILITY_NAME_RE: Final[re.Pattern[str]] = re.compile(CAPABILITY_NAME_PATTERN)


class CapabilityRef(BaseModel):
    """Декларация одной capability с опциональным scope-glob.

    Соответствует таблице ``[[capabilities]]`` в `plugin.toml` /
    `route.toml`. ``name`` валидируется грамматикой
    :data:`CAPABILITY_NAME_PATTERN`; ``scope`` — свободная строка,
    интерпретация делегируется :class:`ScopeMatcher` runtime-gate'а.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    scope: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Проверяет грамматику ``<resource>.<verb>``."""
        if not _CAPABILITY_NAME_RE.match(value):
            raise ValueError(
                f"Invalid capability name {value!r}: expected "
                f"'<resource>.<verb>' matching {CAPABILITY_NAME_PATTERN}"
            )
        return value

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, value: str | None) -> str | None:
        """Запрещает пустую/whitespace-only строку — используй ``None``."""
        if value is not None and not value.strip():
            raise ValueError("scope must be a non-empty string or null")
        return value

    @property
    def resource(self) -> str:
        """Часть до точки (``db`` для ``db.read``)."""
        return self.name.split(".", 1)[0]

    @property
    def verb(self) -> str:
        """Часть после точки (``read`` для ``db.read``)."""
        return self.name.split(".", 1)[1]


DEFAULT_CAPABILITY_CATALOG: Final[tuple[str, ...]] = (
    "db.read",
    "db.write",
    "secrets.read",
    "net.outbound",
    "net.inbound",
    "fs.read",
    "fs.write",
    "mq.publish",
    "mq.consume",
    "cache.read",
    "cache.write",
    "workflow.start",
    "workflow.signal",
    "llm.invoke",
)
"""Имена v0-каталога capabilities из ADR-044."""
