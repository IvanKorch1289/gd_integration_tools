"""Tests для Versioning DSL фасада (S58 W1).

Coverage:
* Continuum end-to-end (INSERT/UPDATE/DELETE → version rows);
* Versioning.get_history / get_version API;
* Versioning.rollback (создаёт новую version row с restored state);
* Versioning.diff (per-column changes + operation names);
* Edge cases: missing entity, missing transaction_id;
* Opt-out models (``__versioned__ = {"versioning": False}``) НЕ трекаются.

Strategy: in-memory SQLite + continuum. Continuum уже настроен в
``src/backend.infrastructure.database.models.base`` (singleton), тесты
используют существующий ``User`` + runtime-defined ``AuditTestModel`` для
изоляции от production data.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, configure_mappers, sessionmaker
from sqlalchemy_continuum import version_class, versioning_manager

from src.backend.dsl.audit_versioning import (
    OP_DELETE,
    OP_INSERT,
    OP_UPDATE,
    Versioning,
    VersioningError,
)
from src.backend.core.domain.models.base import Base, BaseModel

# === Test models (module-level для корректной SQLAlchemy registration) ===


class _AuditTestModel(BaseModel):
    """Test model с versioning — для end-to-end continuum coverage."""

    __tablename__ = "audit_test_model"
    __table_args__ = {"extend_existing": True}
    __versioned__ = {}  # Continuum ON

    name: str = Column(String(50), nullable=False)
    value: int = Column(Integer, default=0)


class _NonVersionedTestModel(BaseModel):
    """Test model БЕЗ versioning — для negative test."""

    __tablename__ = "non_versioned_test_model"
    __table_args__ = {"extend_existing": True}
    __versioned__ = {"versioning": False}  # Continuum OFF

    name: str = Column(String(50), nullable=False)


# === Fixtures ===


@pytest.fixture(scope="module", autouse=True)
def _force_configure_mappers():
    """Force continuum to register all versioned models.

    Continuum populates version_class_map at ``after_configured`` event, который
    срабатывает от ``configure_mappers()``. Вызываем один раз на модуль — после
    этого ``version_class(Model)`` работает для всех моделей с ``__versioned__``.
    """
    configure_mappers()
    yield


@pytest.fixture
def engine() -> Iterator:
    """In-memory SQLite engine с continuum tables + test models."""
    eng = create_engine("sqlite:///:memory:")

    # Continuum needs the transaction table + version tables explicitly
    versioning_manager.create_transaction_model()
    tx_table = versioning_manager.transaction_cls.__table__

    # Original tables
    Base.metadata.create_all(eng)

    # Continuum-managed tables (versioning + transaction)
    tx_table.create(eng, checkfirst=True)
    for model in (_AuditTestModel,):
        try:
            vm = version_class(model)
            vm.__table__.create(eng, checkfirst=True)
        except Exception:
            pass  # Non-versioned model — skip

    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine) -> Iterator:
    """Session factory с auto-rollback."""
    factory = sessionmaker(bind=engine, class_=Session)
    yield factory


@pytest.fixture
def session(session_factory) -> Iterator[Session]:
    """Session с auto-rollback после теста."""
    s = session_factory()
    yield s
    s.rollback()
    s.close()


# === Continuum end-to-end tests ===


def test_continuum_tracks_insert(session: Session) -> None:
    """INSERT → 1 version row (op=0, INSERT) с snapshot всех columns."""
    obj = _AuditTestModel(name="alice", value=10)
    session.add(obj)
    session.commit()

    history = Versioning.get_history(session, _AuditTestModel, obj.id)
    assert len(history) == 1
    v = history[0]
    assert v.operation_type == OP_INSERT
    assert v.name == "alice"
    assert v.value == 10


def test_continuum_tracks_update(session: Session) -> None:
    """UPDATE → 2 version rows: INSERT (op=0) + UPDATE (op=1)."""
    obj = _AuditTestModel(name="alice", value=10)
    session.add(obj)
    session.commit()

    obj.name = "alice2"
    obj.value = 99
    session.commit()

    history = Versioning.get_history(session, _AuditTestModel, obj.id)
    assert len(history) == 2
    assert history[0].operation_type == OP_INSERT
    assert history[1].operation_type == OP_UPDATE
    assert history[1].name == "alice2"
    assert history[1].value == 99


def test_continuum_tracks_delete(session: Session) -> None:
    """DELETE → 3 version rows: INSERT + UPDATE + DELETE (op=2)."""
    obj = _AuditTestModel(name="alice", value=10)
    session.add(obj)
    session.commit()
    obj.name = "alice2"
    session.commit()
    obj_id = obj.id
    session.delete(obj)
    session.commit()

    history = Versioning.get_history(session, _AuditTestModel, obj_id)
    assert len(history) == 3
    assert history[2].operation_type == OP_DELETE
    assert history[2].name == "alice2"  # Last state before delete


def test_continuum_unchanged_column_not_in_diff(session: Session) -> None:
    """UPDATE only 'name', 'value' остаётся — diff показывает только name."""
    obj = _AuditTestModel(name="alice", value=42)
    session.add(obj)
    session.commit()
    obj.name = "alice2"  # value НЕ меняется
    session.commit()

    diff = Versioning.diff(session, _AuditTestModel, obj.id, tx_id_1=1, tx_id_2=2)
    assert "name" in diff["changes"]
    assert diff["changes"]["name"] == {"old": "alice", "new": "alice2"}
    assert "value" not in diff["changes"]  # unchanged


def test_continuum_non_versioned_model_no_history(session: Session) -> None:
    """Non-versioned model (opt-out) → НЕ создаёт version rows."""
    obj = _NonVersionedTestModel(name="bob")
    session.add(obj)
    session.commit()
    obj.name = "bob2"
    session.commit()

    # Non-versioned model: version_class raises
    with pytest.raises(VersioningError):
        Versioning.get_history(session, _NonVersionedTestModel, obj.id)


# === Versioning DSL API tests ===


def test_get_version_specific_transaction(session: Session) -> None:
    """get_version(entity, id, tx) → конкретная version row или None."""
    obj = _AuditTestModel(name="alice")
    session.add(obj)
    session.commit()
    obj.name = "bob"
    session.commit()
    obj.name = "charlie"
    session.commit()

    v1 = Versioning.get_version(session, _AuditTestModel, obj.id, 1)
    v3 = Versioning.get_version(session, _AuditTestModel, obj.id, 3)
    assert v1 is not None and v1.name == "alice"
    assert v3 is not None and v3.name == "charlie"
    assert Versioning.get_version(session, _AuditTestModel, obj.id, 99) is None


def test_rollback_restores_previous_state(session: Session) -> None:
    """rollback(id, tx=1) восстанавливает original к INSERT state → создаёт новую version row."""
    obj = _AuditTestModel(name="alice", value=1)
    session.add(obj)
    session.commit()
    obj.name = "alice2"
    obj.value = 2
    session.commit()
    obj.name = "alice3"
    obj.value = 3
    session.commit()

    # Rollback to tx=1 (INSERT state: name='alice', value=1)
    Versioning.rollback(session, _AuditTestModel, obj.id, transaction_id=1)
    session.commit()

    # After rollback: original has 'alice' / 1, AND a new version row (tx=4) created
    session.refresh(obj)
    assert obj.name == "alice"
    assert obj.value == 1

    history = Versioning.get_history(session, _AuditTestModel, obj.id)
    assert len(history) == 4
    assert history[3].operation_type == OP_UPDATE
    assert history[3].name == "alice"
    assert history[3].value == 1


def test_rollback_raises_on_missing_entity(session: Session) -> None:
    """rollback для несуществующего entity → VersioningError."""
    with pytest.raises(VersioningError, match="not found"):
        Versioning.rollback(session, _AuditTestModel, 99999, transaction_id=1)


def test_rollback_raises_on_missing_transaction(session: Session) -> None:
    """rollback с несуществующим transaction_id → VersioningError."""
    obj = _AuditTestModel(name="alice")
    session.add(obj)
    session.commit()

    with pytest.raises(VersioningError, match="tx=99 not found"):
        Versioning.rollback(session, _AuditTestModel, obj.id, transaction_id=99)


def test_diff_returns_structured_changes(session: Session) -> None:
    """diff возвращает dict с entity, transactions, operation names, changes."""
    obj = _AuditTestModel(name="alice", value=1)
    session.add(obj)
    session.commit()
    obj.name = "alice2"
    obj.value = 99
    session.commit()

    diff = Versioning.diff(session, _AuditTestModel, obj.id, tx_id_1=1, tx_id_2=2)
    assert diff["entity"] == "_AuditTestModel#1" or "_AuditTestModel" in diff["entity"]
    assert diff["from_transaction"] == 1
    assert diff["to_transaction"] == 2
    assert diff["from_operation"] == "INSERT"
    assert diff["to_operation"] == "UPDATE"
    assert diff["changes"]["name"] == {"old": "alice", "new": "alice2"}
    assert diff["changes"]["value"] == {"old": 1, "new": 99}


def test_diff_empty_changes_when_identical(session: Session) -> None:
    """diff между двумя snapshot'ами с одинаковыми values → пустые changes.

    Continuum SKIPS no-op UPDATEs (когда ни одно column не изменилось) — не
    создаёт version row. Поэтому: INSERT + UPDATE 'a'→'b' + UPDATE 'b'→'a'
    даёт 3 transactions (tx=1, tx=2, tx=3), НЕ 4.
    """
    obj = _AuditTestModel(name="alice", value=42)
    session.add(obj)
    session.commit()  # tx=1
    obj.name = "alice_temp"
    session.commit()  # tx=2
    obj.name = "alice"  # back to original
    session.commit()  # tx=3

    diff = Versioning.diff(session, _AuditTestModel, obj.id, tx_id_1=1, tx_id_2=3)
    # Final state (tx=3) = initial state (tx=1) — no changes
    assert diff["changes"] == {}  # No diff between snapshots
    assert diff["from_operation"] == "INSERT"
    assert diff["to_operation"] == "UPDATE"


def test_diff_raises_on_missing_version(session: Session) -> None:
    """diff с несуществующим transaction_id → VersioningError."""
    obj = _AuditTestModel(name="alice")
    session.add(obj)
    session.commit()

    with pytest.raises(VersioningError, match="not found"):
        Versioning.diff(session, _AuditTestModel, obj.id, tx_id_1=1, tx_id_2=99)


def test_operation_name_helper() -> None:
    """_operation_name(int) → INSERT/UPDATE/DELETE string."""
    assert Versioning._operation_name(OP_INSERT) == "INSERT"
    assert Versioning._operation_name(OP_UPDATE) == "UPDATE"
    assert Versioning._operation_name(OP_DELETE) == "DELETE"
    assert Versioning._operation_name(99) == "UNKNOWN(99)"
