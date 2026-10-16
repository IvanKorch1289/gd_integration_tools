"""Tests for ``src.backend.core.auth.auth_context_helpers``.

Sprint 125 W3: utility functions для извлечения tenant_id / groups /
permissions из AuthContext.metadata.

Покрывает 3 функции:
- extract_tenant_id: проверка типа, пустых строк, отсутствия metadata
- extract_user_groups: фильтрация non-str элементов, отсутствия
- extract_user_permissions: список → tuple, scope → префикс scope:,
  None-безопасно (fail-closed)
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.auth.auth_context_helpers import (
    extract_tenant_id,
    extract_user_groups,
    extract_user_permissions,
)


class _Auth:
    """Простой duck-type stand-in для AuthContext (только ``metadata`` attr)."""

    def __init__(self, metadata: Any) -> None:
        self.metadata = metadata


# ── extract_tenant_id ────────────────────────────────────────────────


class TestExtractTenantId:
    """Извлечение tenant_id из AuthContext.metadata."""

    def test_returns_tenant_id(self) -> None:
        auth = _Auth({"tenant_id": "tenant-A"})
        assert extract_tenant_id(auth) == "tenant-A"

    def test_missing_returns_none(self) -> None:
        auth = _Auth({"other": "value"})
        assert extract_tenant_id(auth) is None

    def test_empty_string_returns_none(self) -> None:
        auth = _Auth({"tenant_id": ""})
        assert extract_tenant_id(auth) is None

    def test_non_string_returns_none(self) -> None:
        auth = _Auth({"tenant_id": 123})
        assert extract_tenant_id(auth) is None

    def test_none_metadata_returns_none(self) -> None:
        auth = _Auth(None)
        assert extract_tenant_id(auth) is None

    def test_non_dict_metadata_returns_none(self) -> None:
        auth = _Auth(["tenant-A"])
        assert extract_tenant_id(auth) is None

    def test_object_without_metadata_attr_returns_none(self) -> None:
        class NoMetadata:
            pass

        assert extract_tenant_id(NoMetadata()) is None

    def test_none_auth_does_not_crash(self) -> None:
        """``getattr(None, "metadata", None)`` → None → returns None."""
        assert extract_tenant_id(None) is None


# ── extract_user_groups ──────────────────────────────────────────────


class TestExtractUserGroups:
    """Извлечение IdP groups из AuthContext.metadata."""

    def test_returns_groups(self) -> None:
        auth = _Auth({"groups": ["admins", "users"]})
        assert extract_user_groups(auth) == ["admins", "users"]

    def test_empty_list(self) -> None:
        auth = _Auth({"groups": []})
        assert extract_user_groups(auth) == []

    def test_missing_returns_empty(self) -> None:
        auth = _Auth({"other": "value"})
        assert extract_user_groups(auth) == []

    def test_filters_non_string_items(self) -> None:
        """Non-str элементы (int, None, dict) фильтруются — оставляем только str."""
        auth = _Auth({"groups": ["admin", 42, None, "user", {"x": 1}, ""]})
        # "admin" и "user" — str, остальные отфильтрованы; пустая str тоже str,
        # но не пустая (если оставить — попадёт). В текущей реализации
        # пустая str проходит, т.к. isinstance("", str) == True.
        result = extract_user_groups(auth)
        assert "admin" in result
        assert "user" in result
        assert 42 not in result
        assert None not in result
        assert {"x": 1} not in result

    def test_non_list_returns_empty(self) -> None:
        auth = _Auth({"groups": "not-a-list"})
        assert extract_user_groups(auth) == []

    def test_tuple_accepted(self) -> None:
        """Tuple тоже list-like, но isinstance(tuple, list) == False → empty."""
        # Поведение by design: только list, не tuple
        auth = _Auth({"groups": ("admin", "user")})
        assert extract_user_groups(auth) == []

    def test_none_metadata_returns_empty(self) -> None:
        auth = _Auth(None)
        assert extract_user_groups(auth) == []

    def test_none_auth_does_not_crash(self) -> None:
        assert extract_user_groups(None) == []


# ── extract_user_permissions ─────────────────────────────────────────


class TestExtractUserPermissions:
    """Извлечение permissions из metadata.permissions ИЛИ metadata.scope.

    Приоритет: 1) ``permissions`` (list/tuple of str), 2) ``scope`` (str),
    3) пустой tuple (fail-closed).
    """

    def test_returns_permissions_list(self) -> None:
        auth = _Auth({"permissions": ["role:admin", "scope:credit.read"]})
        assert extract_user_permissions(auth) == (
            "role:admin",
            "scope:credit.read",
        )

    def test_returns_permissions_tuple(self) -> None:
        auth = _Auth({"permissions": ("a", "b")})
        assert extract_user_permissions(auth) == ("a", "b")

    def test_empty_permissions_returns_empty(self) -> None:
        auth = _Auth({"permissions": []})
        assert extract_user_permissions(auth) == ()

    def test_filters_non_string_permissions(self) -> None:
        """Non-str элементы permissions фильтруются; пустые str тоже."""
        auth = _Auth({"permissions": ["valid", 42, None, "another", ""]})
        # "valid" и "another" проходят, "" — тоже str и непустая=False → отфильтрован
        result = extract_user_permissions(auth)
        assert "valid" in result
        assert "another" in result
        assert 42 not in result
        assert None not in result
        # Пустая str "" не проходит проверку ``p for p in ... if p``
        assert "" not in result

    def test_scope_string_split_with_prefix(self) -> None:
        """OAuth-style scope string → ``scope:`` prefix + split by whitespace."""
        auth = _Auth({"scope": "credit.read credit.write"})
        assert extract_user_permissions(auth) == (
            "scope:credit.read",
            "scope:credit.write",
        )

    def test_scope_with_extra_whitespace(self) -> None:
        auth = _Auth({"scope": "  a   b   c  "})
        assert extract_user_permissions(auth) == ("scope:a", "scope:b", "scope:c")

    def test_empty_scope_returns_empty(self) -> None:
        auth = _Auth({"scope": ""})
        assert extract_user_permissions(auth) == ()

    def test_whitespace_only_scope_returns_empty(self) -> None:
        auth = _Auth({"scope": "   "})
        assert extract_user_permissions(auth) == ()

    def test_permissions_takes_priority_over_scope(self) -> None:
        """Если оба ключа есть — permissions выигрывает."""
        auth = _Auth(
            {
                "permissions": ["from-list"],
                "scope": "from-scope",
            }
        )
        assert extract_user_permissions(auth) == ("from-list",)

    def test_non_list_permissions_falls_back_to_scope(self) -> None:
        """Невалидный тип ``permissions`` → fallback на scope."""
        auth = _Auth(
            {
                "permissions": "not-a-list",  # invalid
                "scope": "a b",
            }
        )
        assert extract_user_permissions(auth) == ("scope:a", "scope:b")

    def test_non_string_scope_falls_back_to_empty(self) -> None:
        auth = _Auth({"scope": 12345})
        assert extract_user_permissions(auth) == ()

    def test_missing_both_returns_empty(self) -> None:
        auth = _Auth({"other": "value"})
        assert extract_user_permissions(auth) == ()

    def test_none_metadata_returns_empty(self) -> None:
        auth = _Auth(None)
        assert extract_user_permissions(auth) == ()

    def test_non_dict_metadata_returns_empty(self) -> None:
        auth = _Auth(["permissions", "scope"])
        assert extract_user_permissions(auth) == ()

    @pytest.mark.parametrize("auth", [None, _Auth(None), _Auth({})])
    def test_none_safe_no_crash(self, auth: Any) -> None:
        """``None`` auth допустим — возвращает пустой tuple (fail-closed)."""
        assert extract_user_permissions(auth) == ()
