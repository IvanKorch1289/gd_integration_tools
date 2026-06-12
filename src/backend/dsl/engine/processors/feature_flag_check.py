"""S84 W1 — FeatureFlagCheckProcessor: route-level feature flag gate.

DSL шаг ``feature_flag``: проверяет feature flag (через
:class:`core.tenancy.feature_flag_scope.TenantFeatureFlagResolver`)
и условно останавливает pipeline (через ``exchange.stop()``), если
flag выключен. Полезен для canary-rollout, A/B-тестов, kill-switch
сценариев без необходимости вручную вызывать ``resolver.is_enabled()``
в каждом route handler.

Пример YAML DSL::

    steps:
      - feature_flag:
          flag: new_checkout_flow
          default: false
          stop_on_disabled: true
        output: { should_proceed: bool }

Пример Python DSL::

    .feature_flag(flag="new_checkout_flow", default=False)
    .feature_flag(flag="experimental_ml", stop_on_disabled=True)

Семантика:
    * ``stop_on_disabled=True`` (default) — если flag=False →
      ``exchange.stop()`` (pipeline прерывается с статусом ``skipped``).
    * ``stop_on_disabled=False`` — pipeline продолжается, результат
      проверки сохраняется в ``exchange.properties[output_field]``.
    * При ошибке resolver'а — ``exchange.fail()`` (с сообщением, не silent).
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.feature_flag")


class FeatureFlagCheckProcessor(BaseProcessor):
    """Проверяет feature flag и опционально останавливает pipeline.

    Args:
        flag: Имя feature-flag (например, ``"new_checkout_flow"``).
        default: Значение по умолчанию, если flag не найден.
        stop_on_disabled: ``True`` (default) → ``exchange.stop()`` при
            выключенном flag; ``False`` → только запись результата.
        output_field: Имя поля в ``exchange.properties`` для записи
            результата проверки (default ``"_flag_enabled"``).
        name: Опциональное имя процессора для трассировки.

    Body contract: не используется.
    Output: ``exchange.properties[output_field] = bool`` (всегда).
    """

    side_effect: ClassVar[Any] = "READ"
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        flag: str,
        default: bool = False,
        stop_on_disabled: bool = True,
        output_field: str = "_flag_enabled",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"feature_flag({flag})")
        self._flag = flag
        self._default = default
        self._stop_on_disabled = stop_on_disabled
        self._output_field = output_field

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Проверяет flag через TenantFeatureFlagResolver."""
        try:
            from src.backend.core.tenancy.feature_flag_scope import (
                TenantFeatureFlagResolver,
            )
        except ImportError as exc:
            exchange.fail(f"feature_flag_check: feature_flag_scope unavailable: {exc}")
            return

        try:
            resolver = TenantFeatureFlagResolver()
            enabled = await resolver.is_enabled(self._flag, default=self._default)
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "feature_flag resolver error",
                extra={"flag": self._flag, "error": str(exc)},
            )
            exchange.fail(f"feature_flag_check failed for {self._flag!r}: {exc}")
            return

        # Всегда записываем результат для downstream visibility.
        exchange.properties[self._output_field] = enabled

        if not enabled and self._stop_on_disabled:
            _logger.debug(
                "feature_flag disabled — stopping pipeline",
                extra={"flag": self._flag, "default": self._default},
            )
            # ``exchange.stop()`` (а не fail) — pipeline корректно завершается
            # со статусом ``skipped``. Это позволяет distinguish "flag off" от
            # "реальная ошибка" downstream.
            exchange.stop()
            return

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализация в DSL: ``{feature_flag: {flag, default, stop_on_disabled, output_field}}``."""
        spec: dict[str, Any] = {"flag": self._flag, "default": self._default}
        if not self._stop_on_disabled:
            spec["stop_on_disabled"] = False
        if self._output_field != "_flag_enabled":
            spec["output_field"] = self._output_field
        return {"feature_flag": spec}


__all__ = ("FeatureFlagCheckProcessor",)
