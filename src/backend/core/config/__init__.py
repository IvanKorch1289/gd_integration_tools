"""core/config namespace package (S71 W1 docstring marker).

Модуль констант конфигурации (``constants_settings``) импортируется
в ``src.backend.core.config.base`` — не здесь: ``core/config/__init__.py``
выполняется ДО того, как пакет логирования ``core.logging`` успевает
инициализироваться, а создание настроек в этот момент тянет логирование
(циклический импорт). В ``core.config.base`` тот же импорт безопасен —
там уже создаются ``app_base_settings``/``scheduler_settings``.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
