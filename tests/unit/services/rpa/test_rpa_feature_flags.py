"""RPA feature-флаги: описание не должно противоречить значению по умолчанию.

Cycle 172 (ADR-0370, решение владельца): 5 RPA-флагов имели
``default=True`` при описании «default-OFF до …» — описание врало о
фактическом поведении. Исправлено по паттерну
``tenant_cache_prefix_enabled``: описание явно фиксирует реальное
значение по умолчанию.

Гейт ловит возврат к противоречию для любого RPA-флага в
``core/config/features/{sprints_18_21,sprint19_dx,experimental,infrastructure}.py``.
"""

from __future__ import annotations

import re

from pydantic.fields import FieldInfo

from src.backend.core.config.features.experimental import ExperimentalFlags
from src.backend.core.config.features.infrastructure import InfrastructureFlags
from src.backend.core.config.features.sprint19_dx import Sprint19DXFlags
from src.backend.core.config.features.sprints_18_21 import Sprints1821Flags

_FLAG_CLASSES = (
    Sprints1821Flags,
    Sprint19DXFlags,
    ExperimentalFlags,
    InfrastructureFlags,
)

#: Утверждение «default-OFF» в описании (в любом регистре).
_DEFAULT_OFF = re.compile(r"default[-\s]?off", re.IGNORECASE)

#: Цитата в описании — это отсылка к прежней формулировке, а не утверждение.
_QUOTED = re.compile(r"«[^»]*»")

#: RPA-флаги (по домену, а не по имени) — 5 штук.
_RPA_DOMAIN_FLAGS: tuple[tuple[type, str], ...] = (
    (Sprints1821Flags, "rpa_resilience_wrapper_enabled"),
    (Sprints1821Flags, "desktop_rpa_session_pool_enabled"),
    (Sprints1821Flags, "browser_cookies_redis_persist"),
    (Sprint19DXFlags, "rpa_session_persistence"),
    (InfrastructureFlags, "rpa_ocr_enabled"),
)


def _rpa_flags() -> list[tuple[str, FieldInfo]]:
    """Все RPA-флаги из 4 модулей feature-конфига."""
    out: list[tuple[str, FieldInfo]] = []
    for cls in _FLAG_CLASSES:
        for name, field in cls.model_fields.items():
            if "rpa" in name.lower():
                out.append((f"{cls.__name__}.{name}", field))
    for cls, name in _RPA_DOMAIN_FLAGS:
        qualified = f"{cls.__name__}.{name}"
        if all(qualified != existing for existing, _ in out):
            out.append((qualified, cls.model_fields[name]))
    return out


def test_rpa_flags_present() -> None:
    """В 4 модулях есть 5 RPA-флагов (иначе тест молча ничего не проверяет)."""
    names = [name for name, _ in _rpa_flags()]
    assert len(names) >= 5, f"ожидалось >= 5 RPA-флагов, найдено {names}"


def test_rpa_flag_descriptions_match_defaults() -> None:
    """default=True ⇒ в описании нет утверждения «default-OFF»."""
    contradictions: list[str] = []
    for name, field in _rpa_flags():
        # Цитаты («…») — историческая отсылка, а не утверждение о default.
        description = _QUOTED.sub("", field.description or "")
        if field.default is True and _DEFAULT_OFF.search(description):
            contradictions.append(name)
    assert not contradictions, (
        "описание утверждает default-OFF при default=True: "
        f"{contradictions}"
    )
