"""Wave 13 Q16: неизвестные YAML-ключи больше не отбрасываются молча.

Класс дефекта
-------------
``FilteredSettingsSource._filter_data`` фильтрует данные по ``model_fields``
и отбрасывал всё, чего в модели нет, БЕЗ единого сообщения в лог. Ключ с
опечаткой (``conection_timeout`` вместо ``connection_timeout``) приводил к
тихой потере настройки: значение не применялось, но конфиг выглядел
валидным. ``extra="forbid"`` в моделях на YAML не действует — фильтр
отбрасывает ключ ДО валидации pydantic.

Контракт после фикса:
* неизвестный ключ по-прежнему отбрасывается (поведение загрузки не меняется);
* но в лог уходит WARNING с именем ключа и ``yaml_group``;
* warning выдаётся один раз на источник (без log spam при повторных вызовах).
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.backend.core.config.config_loader import FilteredSettingsSource


class _DemoSettings(BaseSettings):
    """Минимальный Settings-класс для проверки фильтрации."""

    yaml_group: ClassVar[str | None] = "demo"
    model_config = SettingsConfigDict(env_prefix="DEMO_", extra="forbid")

    known_field: int = 1


class _DemoSource(FilteredSettingsSource):
    """Источник с фиксированными данными (без чтения YAML)."""

    def __init__(self, settings_cls: type[BaseSettings], data: dict[str, Any]):
        super().__init__(settings_cls)
        self._data = data

    def _load_data(self) -> dict[str, Any]:
        """Возвращает заранее подготовленные данные."""
        return self._data


class TestUnknownKeysVisibility:
    """Неизвестные ключи отбрасываются, но сообщают об этом в лог."""

    def test_unknown_key_is_dropped_from_result(self) -> None:
        """Неизвестный ключ не попадает в итоговые данные."""
        source = _DemoSource(
            _DemoSettings, {"demo": {"known_field": 2, "typo_field": 3}}
        )
        assert source() == {"known_field": 2}

    def test_unknown_key_is_logged_as_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Отброшенный ключ виден в WARNING вместе с ``yaml_group``."""
        source = _DemoSource(
            _DemoSettings, {"demo": {"known_field": 2, "typo_field": 3}}
        )
        with caplog.at_level(logging.WARNING):
            source()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "неизвестный ключ должен логироваться WARNING'ом"
        message = warnings[-1].getMessage()
        assert "typo_field" in message
        assert "demo" in message

    def test_known_keys_produce_no_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Известные ключи не порождают WARNING."""
        source = _DemoSource(_DemoSettings, {"demo": {"known_field": 2}})
        with caplog.at_level(logging.WARNING):
            source()

        assert not [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_warning_is_emitted_once_per_source(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Повторные вызовы источника не дублируют WARNING."""
        source = _DemoSource(
            _DemoSettings, {"demo": {"known_field": 2, "typo_field": 3}}
        )
        with caplog.at_level(logging.WARNING):
            source()
            source()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    def test_all_unknown_keys_are_listed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """В сообщении перечислены ВСЕ отброшенные ключи источника."""
        source = _DemoSource(
            _DemoSettings, {"demo": {"known_field": 2, "typo_a": 3, "typo_b": 4}}
        )
        with caplog.at_level(logging.WARNING):
            source()

        message = [r for r in caplog.records if r.levelno == logging.WARNING][-1]
        text = message.getMessage()
        assert "typo_a" in text
        assert "typo_b" in text
