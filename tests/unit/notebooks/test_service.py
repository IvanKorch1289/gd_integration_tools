"""Тесты ``NotebookService`` поверх ``InMemoryNotebookRepository``.

Покрывает:
- create (с контентом и без — версионирование от 0);
- get / get_version / list_versions;
- update_content (append-version);
- restore_version (создаёт новую версию с контентом старой);
- list_all (фильтр по тегу, include_deleted, limit/offset, сортировка);
- delete (soft) и блокировка операций над удалёнными.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.services.notebooks.repository import InMemoryNotebookRepository
from src.backend.services.notebooks.service import NotebookService


@pytest.fixture
def service() -> NotebookService:
    """Фикстура — свежий сервис с пустым in-memory репозиторием."""
    return NotebookService(InMemoryNotebookRepository())


async def test_create_without_content_yields_zero_version(
    service: NotebookService,
) -> None:
    """Без контента создаётся пустой notebook без версий."""
    nb = await service.create(title="empty", content="", created_by="u")
    assert nb.title == "empty"
    assert nb.latest_version == 0
    assert nb.versions == []


async def test_create_with_content_creates_first_version(
    service: NotebookService,
) -> None:
    """Контент при создании → первая версия (latest_version=1)."""
    nb = await service.create(title="t", content="hello", created_by="alice")
    assert nb.latest_version == 1
    assert len(nb.versions) == 1
    assert nb.versions[0].content == "hello"
    assert nb.versions[0].changed_by == "alice"
    assert nb.versions[0].version == 1


async def test_create_with_tags_and_metadata(service: NotebookService) -> None:
    """Tags/metadata прокидываются в Notebook."""
    nb = await service.create(
        title="t",
        content="c",
        created_by="u",
        tags=["alpha", "beta"],
        metadata={"src": "test"},
    )
    assert nb.tags == ["alpha", "beta"]
    assert nb.metadata == {"src": "test"}


async def test_get_returns_notebook_copy(service: NotebookService) -> None:
    """``get`` возвращает существующий notebook."""
    created = await service.create(title="t", content="c", created_by="u")
    fetched = await service.get(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == created.title


async def test_get_unknown_returns_none(service: NotebookService) -> None:
    """Несуществующий id → None."""
    assert await service.get("does-not-exist") is None


async def test_update_content_appends_new_version(
    service: NotebookService,
) -> None:
    """``update_content`` создаёт новую версию и инкрементирует latest_version."""
    nb = await service.create(title="t", content="v1", created_by="u")
    updated = await service.update_content(
        notebook_id=nb.id, content="v2", user="bob", summary="second"
    )
    assert updated is not None
    assert updated.latest_version == 2
    assert len(updated.versions) == 2
    assert updated.versions[-1].content == "v2"
    assert updated.versions[-1].changed_by == "bob"
    assert updated.versions[-1].summary == "second"


async def test_update_content_for_unknown_returns_none(
    service: NotebookService,
) -> None:
    """Обновление несуществующего notebook'а → None."""
    result = await service.update_content(
        notebook_id="nope", content="x", user="u"
    )
    assert result is None


async def test_get_version_returns_specific_version(
    service: NotebookService,
) -> None:
    """``get_version`` возвращает конкретную версию по номеру."""
    nb = await service.create(title="t", content="v1", created_by="u")
    await service.update_content(notebook_id=nb.id, content="v2", user="u")

    v1 = await service.get_version(nb.id, 1)
    v2 = await service.get_version(nb.id, 2)
    missing = await service.get_version(nb.id, 99)

    assert v1 is not None and v1.content == "v1"
    assert v2 is not None and v2.content == "v2"
    assert missing is None


async def test_get_version_for_unknown_notebook(service: NotebookService) -> None:
    """Версия несуществующего notebook'а → None."""
    assert await service.get_version("nope", 1) is None


async def test_list_versions_returns_all(service: NotebookService) -> None:
    """``list_versions`` возвращает полный список в порядке append."""
    nb = await service.create(title="t", content="v1", created_by="u")
    await service.update_content(notebook_id=nb.id, content="v2", user="u")
    await service.update_content(notebook_id=nb.id, content="v3", user="u")

    versions = await service.list_versions(nb.id)
    assert [v.version for v in versions] == [1, 2, 3]
    assert [v.content for v in versions] == ["v1", "v2", "v3"]


async def test_list_versions_for_unknown_returns_empty(
    service: NotebookService,
) -> None:
    """Несуществующий notebook → пустой список версий."""
    assert await service.list_versions("nope") == []


async def test_restore_version_creates_new_version_with_old_content(
    service: NotebookService,
) -> None:
    """``restore_version`` добавляет НОВУЮ версию с контентом восстанавливаемой."""
    nb = await service.create(title="t", content="v1", created_by="u")
    await service.update_content(notebook_id=nb.id, content="v2", user="u")
    await service.update_content(notebook_id=nb.id, content="v3", user="u")

    restored = await service.restore_version(notebook_id=nb.id, version=1, user="u")
    assert restored is not None
    assert restored.latest_version == 4  # новая версия поверх трёх
    assert restored.versions[-1].content == "v1"
    assert "restore" in (restored.versions[-1].summary or "").lower()


async def test_restore_unknown_version_returns_none(
    service: NotebookService,
) -> None:
    """Восстановление несуществующей версии → None."""
    nb = await service.create(title="t", content="v1", created_by="u")
    assert (
        await service.restore_version(notebook_id=nb.id, version=99, user="u")
        is None
    )


async def test_list_all_returns_existing_notebooks(
    service: NotebookService,
) -> None:
    """``list_all`` возвращает все notebook'и без фильтров."""
    a = await service.create(title="a", content="", created_by="u")
    b = await service.create(title="b", content="", created_by="u")

    items = await service.list_all()
    ids = {n.id for n in items}
    assert a.id in ids
    assert b.id in ids


async def test_list_all_filters_by_tag(service: NotebookService) -> None:
    """Фильтр по тегу возвращает только notebook'и с этим тегом."""
    await service.create(title="a", content="", created_by="u", tags=["alpha"])
    await service.create(title="b", content="", created_by="u", tags=["beta"])

    items = await service.list_all(tag="alpha")
    titles = [n.title for n in items]
    assert "a" in titles
    assert "b" not in titles


async def test_list_all_excludes_deleted_by_default(
    service: NotebookService,
) -> None:
    """По умолчанию soft-deleted записи не возвращаются."""
    a = await service.create(title="a", content="", created_by="u")
    b = await service.create(title="b", content="", created_by="u")
    await service.delete(b.id)

    items = await service.list_all()
    ids = {n.id for n in items}
    assert a.id in ids
    assert b.id not in ids


async def test_list_all_include_deleted(service: NotebookService) -> None:
    """``include_deleted=True`` возвращает удалённые тоже."""
    a = await service.create(title="a", content="", created_by="u")
    b = await service.create(title="b", content="", created_by="u")
    await service.delete(b.id)

    items = await service.list_all(include_deleted=True)
    ids = {n.id for n in items}
    assert a.id in ids
    assert b.id in ids


async def test_list_all_pagination(service: NotebookService) -> None:
    """``limit`` и ``offset`` ограничивают выдачу."""
    for i in range(5):
        await service.create(title=f"n{i}", content="", created_by="u")

    page1 = await service.list_all(limit=2, offset=0)
    page2 = await service.list_all(limit=2, offset=2)

    assert len(page1) == 2
    assert len(page2) == 2
    assert {n.id for n in page1}.isdisjoint({n.id for n in page2})


async def test_delete_marks_soft_deleted(service: NotebookService) -> None:
    """``delete`` ставит is_deleted=True, но запись остаётся в хранилище."""
    nb = await service.create(title="t", content="", created_by="u")
    ok = await service.delete(nb.id)
    assert ok is True

    # запись остаётся доступной по get (с is_deleted=True)
    fetched = await service.get(nb.id)
    assert fetched is not None
    assert fetched.is_deleted is True


async def test_delete_unknown_returns_false(service: NotebookService) -> None:
    """Удаление несуществующего id → False."""
    assert await service.delete("nope") is False


async def test_update_content_after_delete_returns_none(
    service: NotebookService,
) -> None:
    """Обновление soft-deleted notebook'а → None."""
    nb = await service.create(title="t", content="v1", created_by="u")
    await service.delete(nb.id)
    result = await service.update_content(
        notebook_id=nb.id, content="v2", user="u"
    )
    assert result is None


async def test_restore_version_after_delete_returns_none(
    service: NotebookService,
) -> None:
    """Восстановление версии у soft-deleted notebook'а → None."""
    nb = await service.create(title="t", content="v1", created_by="u")
    await service.delete(nb.id)
    result = await service.restore_version(
        notebook_id=nb.id, version=1, user="u"
    )
    assert result is None


async def test_ensure_indexes_is_noop_for_in_memory(
    service: NotebookService,
) -> None:
    """``ensure_indexes`` для in-memory backend'а — no-op (не падает)."""
    # просто проверяем, что вызов не бросает
    await service.ensure_indexes()
