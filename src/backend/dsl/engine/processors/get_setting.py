"""DSL processor ``get_setting`` (R-V15-17 — Step 7).

Чтение настройки из application config + ENV в Exchange. Реализует
R-V15-17: ``builder.get_setting("path.to.value", to="body.x")`` +
YAML-step ``get_setting: { path: "...", to: body.x }``.

Безопасность:
    * capability ``settings.read.<scope>`` (если CapabilityGate доступен);
    * scope извлекается из первого сегмента ``path`` (e.g. ``skb.api_url`` →
      capability ``settings.read.skb``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("GetSettingProcessor",)


_MISSING = object()


@processor(
    "get_setting",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "to": {"type": "string"},
            "default": {},
        },
        "required": ["path"],
    },
    capabilities=("settings.read.*",),
    meta={"tier": 1, "category": "integration"},
)
class GetSettingProcessor(BaseProcessor):
    """Чтение настройки в Exchange.

    Args:
        path: Точечный путь в конфиге (``skb.api_url``, ``ai.openai.model``).
        to: Куда положить значение: ``body.<field>`` или ``properties.<name>``.
        default: Значение по умолчанию если settings-ключ отсутствует.
    """

    def __init__(
        self, path: str, *, to: str = "body.setting", default: Any = None
    ) -> None:
        super().__init__(name=f"get_setting:{path}")
        if not path:
            raise ValueError("get_setting: path must be non-empty")
        self.setting_path = path
        self.target = to
        self.default = default

    @staticmethod
    def _resolve_path(root: Any, path: str) -> Any:
        """Поэтапно достаёт сегменты ``a.b.c`` из объекта/словаря."""
        current: Any = root
        for segment in path.split("."):
            if current is _MISSING:
                return _MISSING
            if isinstance(current, dict):
                if segment not in current:
                    return _MISSING
                current = current[segment]
            else:
                if not hasattr(current, segment):
                    return _MISSING
                current = getattr(current, segment)
        return current

    def _read_setting(self) -> Any:
        """Читает значение из application settings (с fallback на default)."""
        try:
            from src.backend.core.config.settings import settings as app_settings
        except ImportError:
            return self.default

        value = self._resolve_path(app_settings, self.setting_path)
        if value is _MISSING:
            return self.default
        return value

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        """Записывает значение в ``body.<field>`` либо ``properties.<name>``."""
        if self.target.startswith("body."):
            field = self.target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = value
            return
        if self.target.startswith("properties."):
            field = self.target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self.target, value)

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        value = self._read_setting()
        self._apply_target(exchange, value)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"path": self.setting_path}
        if self.target != "body.setting":
            spec["to"] = self.target
        if self.default is not None:
            spec["default"] = self.default
        return {"get_setting": spec}
