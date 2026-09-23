"""Aggregate-прокси над per-domain ``_overrides`` dict'ами (fix 2026-09-23).

W9 Phase 7 split разнёс override-кэш по submodule (per-domain изоляция —
осознанное решение, см. ``test_w9_p2_13_phase7_workflow_split``). При этом
до-split контракт ``providers.workflow._overrides`` (агрегатная точка:
``.clear()`` в autouse-фикстуре тестов, прямой доступ по ключу) должен
продолжать работать.

``_overrides`` здесь — read/aggregate-прокси: submodule'ы регистрируют свои
dict'ы (``register``), объекты остаются РАЗНЫМИ (изоляция сохраняется),
а агрегат поддерживает ``clear()/getitem/setitem/contains/get`` поверх всех
доменов. Запись через агрегат пишет в первый содержащий ключ либо в
последний зарегистрированный домен (domestic для тест-фикстур).
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from typing import Any

_domains: list[dict[str, Any]] = []


def register(domain_dict: dict[str, Any]) -> None:
    """Зарегистрировать per-domain dict в агрегате (вызывают submodule'ы)."""
    _domains.append(domain_dict)


class _AggregateOverrides(MutableMapping[str, Any]):
    """Двухсторонний aggregate-view над зарегистрированными доменами."""

    def __setitem__(self, key: str, value: Any) -> None:
        for d in _domains:
            if key in d:
                d[key] = value
                return
        _domains[-1][key] = value if _domains else None

    def __getitem__(self, key: str) -> Any:
        for d in _domains:
            if key in d:
                return d[key]
        raise KeyError(key)

    def __delitem__(self, key: str) -> None:
        for d in _domains:
            if key in d:
                del d[key]
                return
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for d in _domains:
            for k in d:
                if k not in seen:
                    seen.add(k)
                    yield k

    def __len__(self) -> int:
        return len({k for d in _domains for k in d})

    def __contains__(self, key: object) -> bool:
        return any(key in d for d in _domains)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        for d in _domains:
            if key in d:
                return d[key]
        return default

    def clear(self) -> None:
        for d in _domains:
            d.clear()


_overrides: _AggregateOverrides = _AggregateOverrides()

__all__ = ("_overrides", "register")
