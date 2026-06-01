"""Тесты Pydantic-моделей ``Notebook`` и ``NotebookVersion``.

Покрывает:
- значения по умолчанию (id/timestamps/versions/tags/metadata);
- обязательные поля и валидацию;
- сериализацию ``model_dump`` round-trip;
- свойство ``current_content`` для пустого и непустого notebook'а;
- append-only семантику ``versions`` (через прямое формирование объекта);
- игнорирование неизвестных полей (``ConfigDict(extra="ignore")``).
"""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.backend.services.notebooks.models import Notebook, NotebookVersion


def test_notebook_defaults_minimal_fields() -> None:
    """Минимально допустимый Notebook: только title и created_by."""
    nb = Notebook(title="My Note", created_by="alice")

    assert nb.title == "My Note"
    assert nb.created_by == "alice"
    assert nb.tags == []
    assert nb.metadata == {}
    assert nb.versions == []
    assert nb.latest_version == 0
    assert nb.is_deleted is False
    # id — hex-строка длиной 32 (uuid4().hex)
    assert isinstance(nb.id, str)
    assert len(nb.id) == 32
    # timestamps — UTC, tz-aware
    assert isinstance(nb.created_at, datetime)
    assert nb.created_at.tzinfo is not None
    assert nb.created_at.utcoffset() == timezone.utc.utcoffset(nb.created_at)


def test_notebook_unique_default_ids() -> None:
    """Каждый Notebook получает уникальный id по умолчанию."""
    a = Notebook(title="A", created_by="u")
    b = Notebook(title="B", created_by="u")
    assert a.id != b.id


def test_notebook_missing_required_fields_raises() -> None:
    """Без title/created_by Pydantic должен бросать ValidationError."""
    with pytest.raises(ValidationError) as exc:
        Notebook()
    errors = {err["loc"][0] for err in exc.value.errors()}
    assert "title" in errors
    assert "created_by" in errors


def test_notebook_extra_fields_are_ignored() -> None:
    """``ConfigDict(extra="ignore")`` молча отбрасывает лишние поля."""
    nb = Notebook(title="T", created_by="u", unknown_field=42)
    dumped = nb.model_dump()
    assert "unknown_field" not in dumped


def test_notebook_version_required_fields() -> None:
    """NotebookVersion требует version, content и changed_by."""
    v = NotebookVersion(version=1, content="hello", changed_by="bob")
    assert v.version == 1
    assert v.content == "hello"
    assert v.changed_by == "bob"
    assert v.summary is None
    assert isinstance(v.changed_at, datetime)
    assert v.changed_at.tzinfo is not None


def test_notebook_version_with_summary() -> None:
    """Поле summary опционально и сохраняется."""
    v = NotebookVersion(
        version=2, content="updated", changed_by="bob", summary="fix typo"
    )
    assert v.summary == "fix typo"


def test_notebook_version_missing_required_fields() -> None:
    """Без version/content/changed_by — ValidationError."""
    with pytest.raises(ValidationError):
        NotebookVersion()


def test_notebook_current_content_empty() -> None:
    """``current_content`` пустой строки для notebook'а без версий."""
    nb = Notebook(title="empty", created_by="u")
    assert nb.current_content == ""


def test_notebook_current_content_returns_last_version() -> None:
    """``current_content`` возвращает контент последней версии в списке."""
    nb = Notebook(
        title="t",
        created_by="u",
        versions=[
            NotebookVersion(version=1, content="v1", changed_by="u"),
            NotebookVersion(version=2, content="v2-final", changed_by="u"),
        ],
        latest_version=2,
    )
    assert nb.current_content == "v2-final"


def test_notebook_serialization_roundtrip() -> None:
    """``model_dump`` → ``model_validate`` сохраняет все поля."""
    nb = Notebook(
        title="round",
        created_by="u",
        tags=["a", "b"],
        metadata={"k": "v"},
        versions=[NotebookVersion(version=1, content="x", changed_by="u")],
        latest_version=1,
    )
    restored = Notebook.model_validate(nb.model_dump())
    assert restored.id == nb.id
    assert restored.tags == ["a", "b"]
    assert restored.metadata == {"k": "v"}
    assert restored.latest_version == 1
    assert len(restored.versions) == 1
    assert restored.versions[0].content == "x"


def test_notebook_tags_independent_per_instance() -> None:
    """default_factory гарантирует независимый список tags для каждого экземпляра."""
    a = Notebook(title="a", created_by="u")
    b = Notebook(title="b", created_by="u")
    a.tags.append("only-a")
    assert b.tags == []
