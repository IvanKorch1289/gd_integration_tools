"""ADR-0393 — RPA-шаги: авторизация, таймаут OCR и достижимость из YAML.

Закрывает дефекты волны 18:

* **(10)** ``fill_form`` / ``run_scenario`` шли в legacy ``processors/web.py``
  без capability-проверки — обход гейта. Теперь обёрнуты в
  ``CapabilityGuardedProcessor``;
* **(11)** ``desktop_rpa`` / ``desktop_pyautogui`` документировали YAML, но
  были недостижимы из YAML (канон ADR-0369) — методы билдера добавлены;
* **(13)** OCR в DSL-шаге остался без таймаута (ADR-0368 починил только
  сервисный OCR-процессор).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import CapabilityGuardedProcessor

pytestmark = pytest.mark.unit

#: Модуль проверяет РЕАЛЬНЫЙ capability-гейт RPA-шагов.
REAL_CAPABILITY_GATE = True


# ── (10) capability для legacy web-шагов ─────────────────────────────────


def test_fill_form_is_capability_guarded() -> None:
    """``fill_form`` обёрнут capability-гейтом ``rpa.browser.fill``."""
    from src.backend.dsl.builder import RouteBuilder

    builder = RouteBuilder.from_("r_rpa_guard", source="http:POST /x")
    builder.fill_form(url="http://example.com", fields={"a": "b"})

    processor = builder._processors[-1]
    assert isinstance(processor, CapabilityGuardedProcessor)
    assert processor.required_capability == "rpa.browser.fill"


def test_run_scenario_is_capability_guarded() -> None:
    """``run_scenario`` обёрнут capability-гейтом ``rpa.browser.navigate``."""
    from src.backend.dsl.builder import RouteBuilder

    builder = RouteBuilder.from_("r_rpa_guard", source="http:POST /x")
    builder.run_scenario(steps=[{"action": "navigate"}])

    processor = builder._processors[-1]
    assert isinstance(processor, CapabilityGuardedProcessor)
    assert processor.required_capability == "rpa.browser.navigate"


async def test_guarded_legacy_step_denied_without_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без декларации capability обёрнутый legacy-шаг не выполняется."""
    from src.backend.core.config.features import feature_flags
    from src.backend.core.security.capabilities.gate import get_capability_gate
    from src.backend.dsl.builder import RouteBuilder

    monkeypatch.setattr(feature_flags, "dsl_capability_gate_enabled", True)
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", False)
    get_capability_gate.cache_clear()

    builder = RouteBuilder.from_("r_rpa_guard", source="http:POST /x")
    builder.fill_form(url="http://example.com", fields={"a": "b"})
    processor = builder._processors[-1]

    exchange = Exchange()
    exchange.meta.route_id = "r_rpa_guard"
    exchange.meta.tenant_id = "tenant-a"

    await processor.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "rpa.browser.fill" in exchange.error


# ── (11) достижимость desktop-шагов из YAML ──────────────────────────────


def test_desktop_rpa_is_reachable_from_yaml_whitelist() -> None:
    """``desktop_rpa`` — публичный метод билдера ⇒ доступен из YAML."""
    from src.backend.dsl.builder import RouteBuilder
    from src.backend.dsl.yaml_loader.build import _is_allowed_processor

    builder = RouteBuilder.from_("r_rpa_guard", source="http:POST /x")

    assert _is_allowed_processor(builder, "desktop_rpa") is True
    assert _is_allowed_processor(builder, "desktop_pyautogui") is True


def test_desktop_rpa_builder_creates_processor() -> None:
    """Метод билдера создаёт процессор с нужной capability."""
    from src.backend.dsl.builder import RouteBuilder

    builder = RouteBuilder.from_("r_rpa_guard", source="http:POST /x")
    builder.desktop_rpa(app="C:/app.exe", action="click")
    builder.desktop_pyautogui(action="screenshot")

    desktop_rpa_proc = builder._processors[0]
    desktop_gui_proc = builder._processors[1]
    assert desktop_rpa_proc.required_capability == "rpa.desktop.invoke"
    assert desktop_gui_proc.required_capability == "rpa.desktop.automate"


def test_desktop_rpa_yaml_spec_builds() -> None:
    """YAML-шаг ``desktop_rpa`` собирается в процессор (ADR-0369)."""
    from src.backend.dsl.builder import RouteBuilder
    from src.backend.dsl.yaml_loader.build import _apply_processor

    builder = RouteBuilder.from_("r_rpa_guard", source="http:POST /x")
    _apply_processor(
        builder,
        {
            "desktop_rpa": {
                "app": "C:/app.exe",
                "action": "click",
                "params": {"selector": {"title": "OK"}},
            }
        },
    )

    assert builder._processors
    assert builder._processors[0].required_capability == "rpa.desktop.invoke"


# ── (13) таймаут OCR ──────────────────────────────────────────────────────


def _png_bytes() -> bytes:
    """Валидный PNG (иначе сработает политика безопасной загрузки, ADR-0388)."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_ocr_step_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """OCR не уложился в лимит → понятная ошибка шага (ADR-0368/0393)."""
    from src.backend.core.security.capabilities.gate import get_capability_gate
    from src.backend.core.security.capabilities.models import CapabilityRef
    from src.backend.dsl.engine.processors.rpa.operations.imageocrprocessor import (
        ImageOcrProcessor,
    )

    get_capability_gate.cache_clear()
    get_capability_gate().declare(
        "r_rpa_guard", [CapabilityRef(name="rpa.image.ocr", scope="**")]
    )

    def _hang(*args: Any, **kwargs: Any) -> str:
        # Синхронное блокирование: pytesseract вызывается в thread'е, а
        # внешний ``asyncio.wait_for`` должен успеть сработать.
        import time

        time.sleep(5)
        return "never"

    monkeypatch.setattr("pytesseract.image_to_string", _hang)

    processor = ImageOcrProcessor(timeout=0.05)
    exchange = Exchange()
    exchange.meta.route_id = "r_rpa_guard"
    exchange.meta.tenant_id = "tenant-a"
    exchange.in_message.body = _png_bytes()

    await processor.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.error is not None
    assert "timed out" in exchange.error


async def test_ocr_step_has_default_timeout() -> None:
    """У OCR-шага есть явный предел ожидания по умолчанию."""
    from src.backend.dsl.engine.processors.rpa.operations.imageocrprocessor import (
        DEFAULT_OCR_TIMEOUT_SECONDS,
        ImageOcrProcessor,
    )

    processor = ImageOcrProcessor()

    assert processor._timeout == DEFAULT_OCR_TIMEOUT_SECONDS
    assert DEFAULT_OCR_TIMEOUT_SECONDS > 0
