"""S67 W4 - state.py part of ad_directory_client decomp.

Per-class file split.

Classes: AdAuthError, AdServerConfig, AdSearchEntry.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.backend.core.auth.ldap_contract import AdServerConfig as _AdServerConfig

AdServerConfig = _AdServerConfig


class AdAuthError(Exception):
    """Ошибка bind/search/credentials в AD/LDAP.

    Используется как единая точка ошибок: invalid credentials,
    server unreachable, search filter rejected.
    """



@dataclass
class AdSearchEntry:
    """Результат AD search.

    Attributes:
        dn: Distinguished Name пользователя.
        attributes: Атрибуты пользователя (mail/displayName/department/...).
        groups: DN всех групп пользователя (resolve'нные через memberOf).
    """

    dn: str
    attributes: Mapping[str, Any]
    groups: tuple[str, ...] = ()
