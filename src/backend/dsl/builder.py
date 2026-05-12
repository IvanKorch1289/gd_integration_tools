"""Фасад ``dsl.builder`` — re-export ``RouteBuilder`` из ``dsl.builders.base``.

Сохраняет совместимость с существующими 23+ callsites
``from src.backend.dsl.builder import RouteBuilder``.

Реальный класс живёт в :mod:`src.backend.dsl.builders.base`; декомпозиция
по миксинам сделана в Wave S1/DSL Foundation (Stage 2.2-2.6).
"""

from __future__ import annotations

from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("RouteBuilder",)
