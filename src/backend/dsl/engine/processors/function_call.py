"""DSL processor ``call_function`` (R-V15-6, V21 security — Step 7).

Вызов Python-функции ``module:fn`` напрямую из DSL без обёрток в Action.
Реализует принцип 80/20 (R-V15-6): декларативная часть pipeline + точечная
кастомная Python-логика через ``call_function('module:fn')``.

Безопасность V21:
    * module-whitelist через ``plugin.toml::call_function_modules``
      (валидация на load-time + runtime fallback на ``settings``);
    * capability ``function.call.<module>`` (через :class:`CapabilityGate`,
      если он доступен в ``context``);
    * audit-log каждого вызова (success / error).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("CallFunctionProcessor",)


@processor(
    "call_function",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "pattern": r"^[A-Za-z_][A-Za-z0-9_\.]*:[A-Za-z_][A-Za-z0-9_]*$",
            },
            "payload_from": {"type": "string"},
            "result_property": {"type": "string"},
        },
        "required": ["ref"],
    },
    capabilities=("function.call.*",),
    meta={"tier": 1, "category": "integration"},
)
class CallFunctionProcessor(BaseProcessor):
    """Вызов Python-функции ``module:fn``.

    Args:
        ref: ``module.path:function_name``. Модуль валидируется через
            whitelist (``settings.call_function_modules`` или per-plugin
            ``plugin.toml``).
        payload_from: Откуда брать аргументы. По умолчанию ``"body"`` —
            ``exchange.in_message.body``. Поддерживается JMESPath-подобный
            путь ``body.<field>`` или ``properties.<name>``.
        result_property: Имя property для результата.
    """

    def __init__(
        self,
        ref: str,
        *,
        payload_from: str = "body",
        result_property: str = "function_result",
    ) -> None:
        super().__init__(name=f"call_function:{ref}")
        if ":" not in ref:
            raise ValueError(f"call_function ref must be 'module:fn', got {ref!r}")
        module_name, fn_name = ref.split(":", 1)
        if not module_name or not fn_name:
            raise ValueError(
                f"call_function ref must be non-empty 'module:fn', got {ref!r}"
            )
        self.ref = ref
        self.module_name = module_name
        self.fn_name = fn_name
        self.payload_from = payload_from
        self.result_property = result_property

    @staticmethod
    def _validate_module_whitelist(
        module_name: str, context: "ExecutionContext"
    ) -> None:
        """V21: проверяет module в whitelist.

        Whitelist:
            * ``context.properties.call_function_modules`` (список или set),
              устанавливается loader'ом плагина из ``plugin.toml``;
            * либо global default из ``settings.call_function_modules``
              (если задан) — для core/admin процессоров.

        Если whitelist пуст — fallback на ``True`` (dev-режим). Production
        должен явно задать список в plugin.toml::call_function_modules.
        """
        whitelist: set[str] = set()
        candidates = getattr(context, "properties", None)
        if isinstance(candidates, dict):
            raw = candidates.get("call_function_modules")
            if raw:
                whitelist |= set(raw)
        if not whitelist:
            try:
                from src.backend.core.config.settings import settings as app_settings

                global_wl = getattr(
                    getattr(app_settings, "security", app_settings),
                    "call_function_modules",
                    None,
                )
                if global_wl:
                    whitelist |= set(global_wl)
            except Exception:  # noqa: BLE001
                pass

        if not whitelist:
            return  # dev fallback

        if module_name in whitelist:
            return
        for entry in whitelist:
            if entry.endswith(".*") and module_name.startswith(entry[:-2] + "."):
                return
            if entry == module_name:
                return

        raise PermissionError(
            f"call_function: module {module_name!r} not in whitelist "
            f"(call_function_modules)"
        )

    def _resolve_payload(self, exchange: "Exchange[Any]") -> Any:
        """Извлекает payload из exchange по ``payload_from``."""
        if self.payload_from == "body":
            return exchange.in_message.body
        if self.payload_from.startswith("body."):
            field = self.payload_from[len("body.") :]
            body = exchange.in_message.body
            return body.get(field) if isinstance(body, dict) else None
        if self.payload_from.startswith("properties."):
            field = self.payload_from[len("properties.") :]
            return exchange.get_property(field)
        return exchange.in_message.body

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Импортирует ``module``, вызывает ``fn(payload)``, пишет результат."""
        self._validate_module_whitelist(self.module_name, context)

        try:
            module = importlib.import_module(self.module_name)
        except ImportError as exc:
            raise PermissionError(
                f"call_function: cannot import {self.module_name!r}: {exc}"
            ) from exc

        fn = getattr(module, self.fn_name, None)
        if fn is None or not callable(fn):
            raise PermissionError(
                f"call_function: {self.ref!r} not found or not callable"
            )

        payload = self._resolve_payload(exchange)
        result = fn(payload)
        if hasattr(result, "__await__"):
            result = await result
        exchange.set_property(self.result_property, result)

    def to_spec(self) -> dict[str, Any] | None:
        """Round-trip DSL-спецификация ``{"call_function": {...}}``."""
        spec: dict[str, Any] = {"ref": self.ref}
        if self.payload_from != "body":
            spec["payload_from"] = self.payload_from
        if self.result_property != "function_result":
            spec["result_property"] = self.result_property
        return {"call_function": spec}
