"""Integration tests для Versioning DSL + continuum end-to-end с проектным User.

S58 W4: доказательство, что ``Versioning`` facade работает с
проектной ``User`` моделью (НЕ runtime-defined), через
проектный ``BaseModel`` / ``mapper_registry`` / init migration
version tables (users_version, transaction).

Эти тесты — regression guard:
* continuum setup в base.py не сломан;
* User versioned (через inherited __versioned__ = {} от BaseModel);
* Versioning facade корректно работает с реальной моделью;
* Transaction tracking работает (mod columns заполняются).

Стратегия: in-memory SQLite, force configure_mappers() в module scope,
создать continuum-managed tables (transaction + users_version).
"""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, configure_mappers, sessionmaker
from sqlalchemy_continuum import version_class, versioning_manager

import extensions.core_entities.users.domain.models as users_module  # S168 W14: was src.backend.core.domain.models.users
from src.backend.core.domain.models.base import Base
from src.backend.dsl.audit_versioning import (
    OP_DELETE,
    OP_INSERT,
    OP_UPDATE,
    Versioning,
    VersioningError,
)


@pytest.fixture(scope="module", autouse=True)
def _setup_continuum():
    """Force continuum mappers configuration на module load.

    Continuum populates ``version_class_map`` на ``after_configured`` event.
    Явный ``configure_mappers()`` гарантирует, что ``version_class(User)``
    работает в момент импорта тестов (а не при первом session query).
    """
    configure_mappers()
    yield


@pytest.fixture
def engine() -> Iterator:
    """In-memory SQLite engine с continuum tables + User."""
    eng = create_engine("sqlite:///:memory:")

    # Continuum Transaction class + table
    versioning_manager.create_transaction_model()
    tx_table = versioning_manager.transaction_cls.__table__

    # Project BaseModel tables (users, etc.)
    Base.metadata.create_all(eng)

    # Continuum-managed tables
    tx_table.create(eng, checkfirst=True)
    UserVersion = version_class(users_module.User)
    UserVersion.__table__.create(eng, checkfirst=True)

    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    s = sessionmaker(bind=engine, class_=Session)()
    yield s
    s.rollback()
    s.close()


# === Continuum end-to-end с User моделью ===


def test_user_model_is_versioned() -> None:
    """User наследует __versioned__ от BaseModel → versioned=True."""
    assert getattr(users_module.User, "__versioned__", None) == {}
    UV = version_class(users_module.User)
    assert UV is not None
    assert UV.__table__.name == "users_version"


def test_insert_user_creates_version_row(session: Session) -> None:
    """INSERT User → version row с snapshot всех columns (включая password)."""
    user = users_module.User(
        username=f"alice_{uuid.uuid4().hex[:6]}",
        email="alice@example.com",
        password="hashed_argon2",
        is_active=True,
    )
    session.add(user)
    session.commit()

    history = Versioning.get_history(session, users_module.User, user.id)
    assert len(history) == 1
    v1 = history[0]
    assert v1.operation_type == OP_INSERT
    assert v1.username == user.username
    assert v1.email == "alice@example.com"
    assert v1.is_active is True


def test_update_user_email_creates_diff_version(session: Session) -> None:
    """UPDATE email → новый version row с diff (только email изменён)."""
    user = users_module.User(
        username=f"bob_{uuid.uuid4().hex[:6]}",
        email="bob1@example.com",
        password="hash1",
    )
    session.add(user)
    session.commit()
    user.email = "bob2@example.com"
    session.commit()

    diff = Versioning.diff(session, users_module.User, user.id, tx_id_1=1, tx_id_2=2)
    assert diff["from_operation"] == "INSERT"
    assert diff["to_operation"] == "UPDATE"
    # email изменился
    assert "email" in diff["changes"]
    assert diff["changes"]["email"]["old"] == "bob1@example.com"
    assert diff["changes"]["email"]["new"] == "bob2@example.com"
    # username, is_active, is_superuser, password НЕ изменились
    assert "username" not in diff["changes"]
    assert "is_active" not in diff["changes"]


def test_update_user_active_flag_audit_trail(session: Session) -> None:
    """Активация/деактивация пользователя (security event) → version row."""
    user = users_module.User(
        username=f"charlie_{uuid.uuid4().hex[:6]}", password="h", is_active=True
    )
    session.add(user)
    session.commit()

    # Admin deactivates user
    user.is_active = False
    session.commit()
    # Admin reactivates user
    user.is_active = True
    session.commit()

    history = Versioning.get_history(session, users_module.User, user.id)
    assert len(history) == 3
    assert history[1].operation_type == OP_UPDATE
    assert history[1].is_active is False  # tx=2: deactivated
    assert history[2].operation_type == OP_UPDATE
    assert history[2].is_active is True  # tx=3: reactivated

    # Diff between INSERT (active=True) and final (active=True) — пустой
    diff = Versioning.diff(session, users_module.User, user.id, tx_id_1=1, tx_id_2=3)
    assert diff["changes"] == {}  # Net effect: back to initial


def test_delete_user_creates_delete_version(session: Session) -> None:
    """DELETE User → version row с last state (op=DELETE)."""
    user = users_module.User(
        username=f"dave_{uuid.uuid4().hex[:6]}", password="h", is_active=True
    )
    session.add(user)
    session.commit()
    user_id = user.id

    session.delete(user)
    session.commit()

    history = Versioning.get_history(session, users_module.User, user_id)
    assert len(history) == 2
    delete_v = history[1]
    assert delete_v.operation_type == OP_DELETE
    # Last state before delete preserved
    assert delete_v.username == user.username


def test_get_version_specific_tx(session: Session) -> None:
    """get_version(id, tx) → конкретная версия по transaction_id."""
    user = users_module.User(username=f"eve_{uuid.uuid4().hex[:6]}", password="h")
    session.add(user)
    session.commit()
    user.username = "eve_renamed"
    session.commit()

    v1 = Versioning.get_version(session, users_module.User, user.id, 1)
    v2 = Versioning.get_version(session, users_module.User, user.id, 2)
    assert v1 is not None and v1.username.startswith("eve_")
    assert v2 is not None and v2.username == "eve_renamed"
    # Non-existent tx → None
    assert Versioning.get_version(session, users_module.User, user.id, 99) is None


def test_rollback_to_insert_state(session: Session) -> None:
    """Rollback к INSERT state → новая version row с original values."""
    user = users_module.User(
        username=f"frank_{uuid.uuid4().hex[:6]}",
        email="frank@old.com",
        password="hash_v1",
    )
    session.add(user)
    session.commit()
    original_username = user.username
    original_email = user.email

    # User changes email
    user.email = "frank@new.com"
    session.commit()
    # And changes username
    user.username = original_username + "_renamed"
    session.commit()

    # Admin: rollback to INSERT state (tx=1)
    Versioning.rollback(session, users_module.User, user.id, transaction_id=1)
    session.commit()

    # After rollback: user has original values
    session.refresh(user)
    assert user.email == original_email
    assert user.username == original_username

    # 4 version rows now: INSERT + UPDATE (email) + UPDATE (username) + UPDATE (rollback)
    history = Versioning.get_history(session, users_module.User, user.id)
    assert len(history) == 4
    assert history[3].operation_type == OP_UPDATE
    assert history[3].email == original_email
    assert history[3].username == original_username


def test_diff_raises_on_missing_user(session: Session) -> None:
    """diff для несуществующего user_id → VersioningError."""
    # Add a user to ensure there's at least one entity in the table
    user = users_module.User(username=f"ghost_{uuid.uuid4().hex[:6]}", password="h")
    session.add(user)
    session.commit()

    with pytest.raises(VersioningError, match="not found"):
        Versioning.diff(session, users_module.User, 99999, tx_id_1=1, tx_id_2=2)


def test_rollback_raises_on_missing_user(session: Session) -> None:
    """rollback для несуществующего user_id → VersioningError."""
    with pytest.raises(VersioningError, match="not found"):
        Versioning.rollback(session, users_module.User, 99999, transaction_id=1)
