"""Tests для ``Versioning.purge_old_versions`` (S61 W2 retention policy).

Coverage:
* ``retention_days <= 0`` → VersioningError;
* ``batch_size <= 0`` → VersioningError;
* Empty DB (no transactions) → zero counts, no error;
* Dry run: counts but does NOT delete;
* Реальный purge удаляет version rows и transactions старше cutoff;
* Недавние transactions (внутри retention window) НЕ удаляются;
* ``remaining`` корректно отражает не-deleted old rows;
* Non-versioned models не мешают purge (проверка ClassNotVersioned handling);
* Multi-batch (batch_size < total) → scanned == batch_size.
"""

# ruff: noqa: S101, S106  # assert, hardcoded test creds

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, configure_mappers, sessionmaker
from sqlalchemy_continuum import version_class, versioning_manager

from src.backend.dsl.audit_versioning import Versioning, VersioningError
from src.backend.infrastructure.database.models.base import Base, BaseModel


class _PurgeTestModel(BaseModel):
    """Test model с versioning — для end-to-end retention coverage."""

    __tablename__ = "purge_test_model"
    __table_args__ = {"extend_existing": True}
    __versioned__ = {}

    name: str = Column(String(50), nullable=False)
    value: int = Column(Integer, default=0)


class _NonVersionedForPurge(BaseModel):
    """Opt-out model — не должна мешать purge loop."""

    __tablename__ = "non_versioned_purge_model"
    __table_args__ = {"extend_existing": True}
    __versioned__ = {"versioning": False}

    label: str = Column(String(50))


@pytest.fixture(scope="module", autouse=True)
def _force_configure_mappers() -> Iterator[None]:
    configure_mappers()
    yield


@pytest.fixture
def engine() -> Iterator:
    eng = create_engine("sqlite:///:memory:")
    versioning_manager.create_transaction_model()
    Base.metadata.create_all(eng)
    tx_table = versioning_manager.transaction_cls.__table__
    tx_table.create(eng, checkfirst=True)
    for model in (_PurgeTestModel,):
        try:
            vm = version_class(model)
            vm.__table__.create(eng, checkfirst=True)
        except Exception:
            pass
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: object) -> Iterator:
    factory = sessionmaker(bind=engine, class_=Session)
    yield factory


@pytest.fixture
def session(session_factory: object) -> Iterator[Session]:
    s = session_factory()
    yield s
    s.rollback()
    s.close()


# ── input validation ─────────────────────────────────────────────────────


def test_purge_rejects_zero_retention(session: Session) -> None:
    with pytest.raises(VersioningError, match="retention_days должен быть > 0"):
        Versioning.purge_old_versions(session, retention_days=0)


def test_purge_rejects_negative_retention(session: Session) -> None:
    with pytest.raises(VersioningError, match="retention_days должен быть > 0"):
        Versioning.purge_old_versions(session, retention_days=-1)


def test_purge_rejects_zero_batch(session: Session) -> None:
    with pytest.raises(VersioningError, match="batch_size должен быть > 0"):
        Versioning.purge_old_versions(session, retention_days=90, batch_size=0)


# ── empty DB ─────────────────────────────────────────────────────────────


def test_purge_empty_db_returns_zeros(session: Session) -> None:
    """Пустая DB: все counters = 0, no error."""
    result = Versioning.purge_old_versions(session, retention_days=90)
    assert result == {
        "scanned": 0,
        "deleted_transactions": 0,
        "deleted_versions": 0,
        "remaining": 0,
    }


# ── data setup helpers ───────────────────────────────────────────────────


def _backdate_transaction(
    session: Session, model: type, days_ago: int, **kwargs: object
) -> int:
    """Создаёт versioned row + backdate его transaction.issued_at."""
    obj = model(**kwargs)
    session.add(obj)
    session.commit()
    tx_id = obj.versions[0].transaction_id
    Transaction = versioning_manager.transaction_cls
    new_issued = datetime.now(timezone.utc) - timedelta(days=days_ago)
    session.query(Transaction).filter(Transaction.id == tx_id).update(
        {"issued_at": new_issued}, synchronize_session=False
    )
    session.commit()
    session.expire_all()
    return tx_id


# ── dry_run ──────────────────────────────────────────────────────────────


def test_purge_dry_run_does_not_delete(session: Session) -> None:
    """dry_run=True: counts scanned, но не удаляет."""
    _backdate_transaction(session, _PurgeTestModel, days_ago=100, name="old1", value=1)
    _backdate_transaction(session, _PurgeTestModel, days_ago=100, name="old2", value=2)

    result = Versioning.purge_old_versions(
        session, retention_days=90, dry_run=True
    )

    assert result["scanned"] == 2
    assert result["deleted_transactions"] == 0
    assert result["deleted_versions"] == 0
    # Verify данные всё ещё на месте
    history = Versioning.get_history(session, _PurgeTestModel, 1)
    assert len(history) >= 1


# ── real purge ───────────────────────────────────────────────────────────


def test_purge_deletes_old_transactions_and_versions(session: Session) -> None:
    """Real purge удаляет и transactions, и version rows старше cutoff."""
    _backdate_transaction(session, _PurgeTestModel, days_ago=100, name="old", value=1)

    result = Versioning.purge_old_versions(session, retention_days=90)

    assert result["scanned"] == 1
    assert result["deleted_transactions"] == 1
    assert result["deleted_versions"] >= 1  # минимум 1 version row для INSERT
    assert result["remaining"] == 0


def test_purge_preserves_recent_transactions(session: Session) -> None:
    """Transactions внутри retention window НЕ удаляются."""
    _backdate_transaction(
        session, _PurgeTestModel, days_ago=10, name="recent", value=1
    )

    result = Versioning.purge_old_versions(session, retention_days=90)

    assert result["scanned"] == 0
    assert result["deleted_transactions"] == 0
    assert result["deleted_versions"] == 0
    # История сохранилась
    history = Versioning.get_history(session, _PurgeTestModel, 1)
    assert len(history) == 1


def test_purge_mixed_old_and_recent(session: Session) -> None:
    """Mixed: old удаляются, recent остаются."""
    _backdate_transaction(session, _PurgeTestModel, days_ago=120, name="old", value=1)
    _backdate_transaction(session, _PurgeTestModel, days_ago=5, name="recent", value=2)

    result = Versioning.purge_old_versions(session, retention_days=90)

    assert result["scanned"] == 1
    assert result["deleted_transactions"] == 1
    # recent row всё ещё здесь
    history = Versioning.get_history(session, _PurgeTestModel, 2)
    assert len(history) == 1
    assert history[0].name == "recent"


# ── batch_size pagination ────────────────────────────────────────────────


def test_purge_respects_batch_size(session: Session) -> None:
    """batch_size=1 → scanned=1, remaining > 0 (есть ещё)."""
    for i in range(3):
        _backdate_transaction(
            session, _PurgeTestModel, days_ago=100, name=f"old{i}", value=i
        )

    result = Versioning.purge_old_versions(session, retention_days=90, batch_size=1)

    assert result["scanned"] == 1
    assert result["deleted_transactions"] == 1
    assert result["remaining"] == 2  # ещё 2 old transactions


# ── non-versioned model safety ───────────────────────────────────────────


def test_purge_ignores_non_versioned_models(session: Session) -> None:
    """Opt-out модель не вызывает падения purge loop (ClassNotVersioned handled)."""
    # Создаём row в non-versioned — continuum НЕ должен создать transaction
    obj = _NonVersionedForPurge(label="x")
    session.add(obj)
    session.commit()

    # Создаём старую versioned transaction
    _backdate_transaction(session, _PurgeTestModel, days_ago=100, name="y", value=1)

    result = Versioning.purge_old_versions(session, retention_days=90)

    assert result["deleted_transactions"] == 1
    # non-versioned row не пострадал
    assert session.query(_NonVersionedForPurge).count() == 1


# ── multiple versioned models ────────────────────────────────────────────


class _SecondVersioned(BaseModel):
    """Вторая versioned модель — для проверки purge по ВСЕМ version tables."""

    __tablename__ = "second_versioned_purge"
    __table_args__ = {"extend_existing": True}
    __versioned__ = {}

    title: str = Column(String(50))


@pytest.fixture(scope="module", autouse=True)
def _register_second_model() -> Iterator[None]:
    """Регистрация второй versioned модели — один раз на модуль."""
    try:
        version_class(_SecondVersioned)
        # таблица создаётся через engine fixture
    except Exception:
        pass
    yield


def test_purge_cascades_across_multiple_versioned_models(
    engine: object,
) -> None:
    """Purge удаляет version rows из ВСЕХ version tables (multi-model)."""
    # Создаём second_versioned table
    vm = version_class(_SecondVersioned)
    vm.__table__.create(engine, checkfirst=True)  # type: ignore[arg-type]

    Session_ = sessionmaker(bind=engine, class_=Session)
    s = Session_()
    try:
        _backdate_transaction(s, _PurgeTestModel, days_ago=100, name="a", value=1)
        _backdate_transaction(s, _SecondVersioned, days_ago=100, title="b")

        result = Versioning.purge_old_versions(s, retention_days=90)

        assert result["scanned"] == 2
        assert result["deleted_transactions"] == 2
        # >= 2 version rows (по одному INSERT на каждую модель)
        assert result["deleted_versions"] >= 2
        assert result["remaining"] == 0
    finally:
        s.rollback()
        s.close()
