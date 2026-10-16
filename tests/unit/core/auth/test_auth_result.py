"""Tests for ``src.backend.core.auth.auth_result``.

S61 M2-#1 split: AuthResult extracted из facade god-object.
Pure data class, no behavior, no I/O. Frozen + slots + dataclass.

Тесты фиксируют контракт:
- default values для optional fields
- immutability (frozen → raises FrozenInstanceError)
- equality (dataclass auto __eq__)
- None vs empty list/dict семантика
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from typing import Any

import pytest

from src.backend.core.auth.auth_result import AuthResult


class TestAuthResultConstruction:
    """Базовое создание и defaults."""

    def test_minimal_construction(self) -> None:
        """Только ``is_authenticated`` обязателен; остальное имеет defaults."""
        r = AuthResult(is_authenticated=True)
        assert r.is_authenticated is True
        assert r.method is None
        assert r.subject is None
        assert r.tenant_id is None
        assert r.groups == []
        assert r.capabilities == []
        assert r.metadata == {}

    def test_full_construction(self) -> None:
        r = AuthResult(
            is_authenticated=True,
            method="jwt",
            subject="user-123",
            tenant_id="tenant-A",
            groups=["admins", "users"],
            capabilities=["read", "write"],
            metadata={"raw_claim": "value"},
        )
        assert r.method == "jwt"
        assert r.subject == "user-123"
        assert r.tenant_id == "tenant-A"
        assert r.groups == ["admins", "users"]
        assert r.capabilities == ["read", "write"]
        assert r.metadata == {"raw_claim": "value"}

    def test_unauthenticated(self) -> None:
        r = AuthResult(is_authenticated=False)
        assert r.is_authenticated is False


class TestAuthResultDefaults:
    """Каждый optional field имеет корректный default (mutable types — factory)."""

    def test_groups_default_is_list(self) -> None:
        """``field(default_factory=list)`` — НЕ shared mutable между инстансами."""
        r1 = AuthResult(is_authenticated=True)
        r2 = AuthResult(is_authenticated=True)
        r1.groups.append("admin")
        # r2 не должен видеть изменение
        assert r2.groups == []
        assert r1.groups == ["admin"]

    def test_capabilities_default_is_list(self) -> None:
        r1 = AuthResult(is_authenticated=True)
        r2 = AuthResult(is_authenticated=True)
        r1.capabilities.append("read")
        assert r2.capabilities == []

    def test_metadata_default_is_dict(self) -> None:
        r1 = AuthResult(is_authenticated=True)
        r2 = AuthResult(is_authenticated=True)
        r1.metadata["k"] = "v"
        assert r2.metadata == {}


class TestAuthResultImmutability:
    """Frozen dataclass — frozen-защита только для top-level assignment.

    ``@dataclass(frozen=True)`` запрещает ``obj.field = ...``, но **не**
    запрещает мутацию mutable-полей (list/dict) in-place. Это известное
    ограничение ``frozen=True`` (для глубокой защиты нужен отдельный слой
    типа ``attrs.frozen`` или ``pydantic``).
    """

    def test_top_level_assignment_raises(self) -> None:
        r = AuthResult(is_authenticated=True)
        with pytest.raises(FrozenInstanceError):
            r.is_authenticated = False  # type: ignore[misc]

    def test_top_level_method_assignment_raises(self) -> None:
        r = AuthResult(is_authenticated=True)
        with pytest.raises(FrozenInstanceError):
            r.method = "saml"  # type: ignore[misc]

    def test_mutable_list_field_in_place_works(self) -> None:
        """Documented Py3.12+ поведение: frozen не защищает in-place мутацию."""
        r = AuthResult(is_authenticated=True, groups=["a"])
        # Не бросает (см. docstring)
        r.groups.append("b")
        assert r.groups == ["a", "b"]

    def test_mutable_dict_field_in_place_works(self) -> None:
        r = AuthResult(is_authenticated=True)
        r.metadata["k"] = "v"
        assert r.metadata == {"k": "v"}


class TestAuthResultEquality:
    """Dataclass auto-__eq__ — два инстанса с одинаковыми полями равны."""

    def test_equal_when_same_fields(self) -> None:
        r1 = AuthResult(
            is_authenticated=True,
            method="jwt",
            subject="user-1",
        )
        r2 = AuthResult(
            is_authenticated=True,
            method="jwt",
            subject="user-1",
        )
        assert r1 == r2

    def test_not_equal_when_different(self) -> None:
        r1 = AuthResult(is_authenticated=True, method="jwt")
        r2 = AuthResult(is_authenticated=True, method="saml")
        assert r1 != r2

    def test_not_equal_different_subject(self) -> None:
        r1 = AuthResult(is_authenticated=True, subject="a")
        r2 = AuthResult(is_authenticated=True, subject="b")
        assert r1 != r2


class TestAuthResultHashing:
    """Frozen dataclass с mutable-полями — NOT hashable by default.

    Python 3.12+ отказывается генерировать ``__hash__`` для frozen dataclass
    если есть mutable поля (list/dict) — TypeError при попытке hash.
    Это **by design** для предотвращения inconsistent hashing.
    """

    def test_unhashable_due_to_mutable_fields(self) -> None:
        r = AuthResult(is_authenticated=True, method="jwt")
        with pytest.raises(TypeError, match="unhashable"):
            hash(r)

    def test_unhashable_with_empty_mutables(self) -> None:
        """Даже пустые list/dict делают frozen dataclass unhashable."""
        r = AuthResult(is_authenticated=True)
        with pytest.raises(TypeError, match="unhashable"):
            hash(r)


class TestAuthResultRepr:
    """Dataclass auto __repr__ — для отладки и логирования."""

    def test_repr_contains_field(self) -> None:
        r = AuthResult(is_authenticated=True, subject="user-1")
        text = repr(r)
        assert "AuthResult" in text
        assert "is_authenticated=True" in text
        assert "subject='user-1'" in text


class TestAuthResultFields:
    """Проверка, что dataclass-fields соответствуют заявленному контракту.

    С ``from __future__ import annotations`` типы хранятся как строки
    (lazy evaluation); проверяем строковое представление.
    """

    def test_field_names(self) -> None:
        names = {f.name for f in fields(AuthResult)}
        assert names == {
            "is_authenticated",
            "method",
            "subject",
            "tenant_id",
            "groups",
            "capabilities",
            "metadata",
        }

    @pytest.mark.parametrize(
        "name,expected_type_str",
        [
            ("is_authenticated", "bool"),
            ("method", "str | None"),
            ("subject", "str | None"),
            ("tenant_id", "str | None"),
            ("groups", "list[str]"),
            ("capabilities", "list[str]"),
            ("metadata", "dict[str, Any]"),
        ],
    )
    def test_field_type_annotation(
        self, name: str, expected_type_str: str
    ) -> None:
        """Аннотации (как строки из-за future-annotations) совпадают с контрактом."""
        f = next(f for f in fields(AuthResult) if f.name == name)
        assert f.type == expected_type_str
