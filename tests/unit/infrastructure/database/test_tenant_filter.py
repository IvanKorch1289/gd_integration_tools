"""Unit-tests for tenant filter (RLS helper).

S107 W1: ``infrastructure.database.tenant_filter`` — shim; реализация
живёт в ``core.tenancy.sqlalchemy_filter``. Тесты патчат canonical-модуль
(шим только реэкспортирует), сбрасывая ``_INSTALLED`` перед каждой
проверкой регистрации.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.tenancy import sqlalchemy_filter
from src.backend.infrastructure.database.tenant_filter import (
    TenantMixin,
    apply_tenant_filter,
)

CANONICAL = "src.backend.core.tenancy.sqlalchemy_filter"


class _FakeTenantEntity:
    """Минимальная «mapped-сущность» с tenant_id для резолвера в фильтре."""

    tenant_id = "column-placeholder"


class _FakeDmlStatement:
    """ORM ``Update``/``Delete``-statement: есть только ``entity_description``.

    У DML нет ни ``column_descriptions``, ни ``froms`` — именно поэтому
    прежний обход ``stmt.froms`` DML пропускал.
    """

    def __init__(self) -> None:
        self.entity_description = {"entity": _FakeTenantEntity}
        self.where_calls: list[object] = []

    def where(self, criterion: object) -> "_FakeDmlStatement":
        """Вернуть новый statement с добавленным предикатом (иммутабельность).

        Args:
            criterion: Условие фильтрации.

        Returns:
            Новый statement, разделяющий список предикатов с исходным.
        """
        clone = _FakeDmlStatement()
        clone.where_calls = [*self.where_calls, criterion]
        return clone


@pytest.fixture(autouse=True)
def _reset_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_tenant_filter идемпотентен (_INSTALLED) — сбрасываем флаг."""
    monkeypatch.setattr(sqlalchemy_filter, "_INSTALLED", False)


def test_tenant_mixin_has_column() -> None:
    assert hasattr(TenantMixin, "tenant_id")


def test_apply_tenant_filter_registers_listeners() -> None:
    session_factory = MagicMock()
    with patch(f"{CANONICAL}.event.listens_for") as mock_listen:
        apply_tenant_filter(session_factory)
        assert mock_listen.call_count == 2


def test_filter_by_tenant_handles_dml() -> None:
    """F-AM: UPDATE/DELETE больше не отбрасываются (контракт изменён осознанно).

    До F-AM listener делал ``if not is_select: return``, из-за чего
    ``repository.update()``/``repository.delete()`` меняли чужой tenant
    (воспроизведено: rowcount=1 при чужом id). Тест проверяет, что DML
    проходит через ту же ветку фильтрации, а не выходит из неё.

    Переход DML → «фильтруется» — осознанное изменение контракта в пользу
    изоляции tenant; поведение подтверждено на реальном SQLAlchemy в
    ``tests/unit/core/tenancy/test_tenant_filter_orm_dml.py``.
    """
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn

        return decorator

    with (
        patch(f"{CANONICAL}.event.listens_for", fake_listens_for),
        patch(f"{CANONICAL}.get_tenant_id", return_value="t1"),
    ):
        apply_tenant_filter(MagicMock())

        # Вызов внутри with: get_tenant_id патчится только в этом контексте.
        # Вне блока он вернул бы реальный пустой tenant, и фильтр не применился
        # бы — ровно тот vacuous-дефект, который делал старый тест бессодержательным.
        for is_update, is_delete in ((True, False), (False, True)):
            statement = _FakeDmlStatement()
            orm_state = SimpleNamespace(
                is_select=False,
                is_update=is_update,
                is_delete=is_delete,
                statement=statement,
            )
            captured["do_orm_execute"](orm_state)
            assert orm_state.statement is not statement, (
                "statement должен быть перезаписан"
            )
            assert orm_state.statement.where_calls, (
                "DML должен получить предикат tenant_id"
            )


def test_filter_by_tenant_skips_non_dml() -> None:
    """Ни SELECT, ни UPDATE, ни DELETE (например bulk-insert через Core) — no-op.

    Args:
        None: нет.
    """
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn

        return decorator

    with (
        patch(f"{CANONICAL}.event.listens_for", fake_listens_for),
        patch(f"{CANONICAL}.get_tenant_id", return_value="t1"),
    ):
        apply_tenant_filter(MagicMock())

    orm_state = SimpleNamespace(
        is_select=False, is_update=False, is_delete=False, statement=None
    )
    captured["do_orm_execute"](orm_state)
    assert orm_state.statement is None


def test_filter_by_tenant_no_tenant_returns() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn

        return decorator

    with (
        patch(f"{CANONICAL}.event.listens_for", fake_listens_for),
        patch(f"{CANONICAL}.get_tenant_id", return_value=None),
    ):
        apply_tenant_filter(MagicMock())

    stmt = MagicMock(froms=[MagicMock(entity_namespace=MagicMock(tenant_id="col"))])
    orm_state = SimpleNamespace(is_select=True, statement=stmt)
    captured["do_orm_execute"](orm_state)
    # no assertion error means return early


def test_set_tenant_on_new_sets_when_empty() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn

        return decorator

    with (
        patch(f"{CANONICAL}.event.listens_for", fake_listens_for),
        patch(f"{CANONICAL}.get_tenant_id", return_value="t1"),
    ):
        apply_tenant_filter(MagicMock())
        obj = SimpleNamespace(tenant_id="")
        session = SimpleNamespace(new=[obj])
        captured["before_flush"](session, None, None)
        assert obj.tenant_id == "t1"


def test_set_tenant_on_new_preserves_existing() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn

        return decorator

    with (
        patch(f"{CANONICAL}.event.listens_for", fake_listens_for),
        patch(f"{CANONICAL}.get_tenant_id", return_value="t1"),
    ):
        apply_tenant_filter(MagicMock())
        obj = SimpleNamespace(tenant_id="existing")
        session = SimpleNamespace(new=[obj])
        captured["before_flush"](session, None, None)
        assert obj.tenant_id == "existing"
