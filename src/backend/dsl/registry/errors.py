"""Исключения для ProcessorRegistry (Stage 3, V15 Sprint 1).

См. ``processor.py`` и план
``/home/user/.claude/plans/replicated-seeking-panda.md`` (раздел A5/Stage 3).
"""

from __future__ import annotations


class ProcessorRegistryError(Exception):
    """Базовое исключение реестра процессоров."""


class ProcessorConflictError(ProcessorRegistryError):
    """Регистрируемое имя занято и не предоставлен ``replaces=``-явный override.

    Возникает, если плагин пытается зарегистрировать процессор под уже
    использованным namespace:name без явного указания, что замещается
    существующая регистрация.
    """


class CapabilityDeniedError(ProcessorRegistryError):
    """Плагин обращается к ресурсу/возможности, не указанной в ``plugin.toml``.

    Используется capability-gate (V11.1):
    * ``processor.override.<name>`` — для замещения встроенного процессора.
    * ``function.call.<module>`` — для разрешения вызова модуля через
      ``call_function('module:fn')``.
    * ``settings.read.<scope>`` — для чтения настроек через ``get_setting()``.
    """


class ProcessorNotFoundError(ProcessorRegistryError, KeyError):
    """Запрошен процессор, не зарегистрированный в реестре."""
