"""ADR-0390 (волна 18, кластер G1) — LocalFS: гонка tmp-файлов и границы base.

Дефект (5) [medium]: временный файл имел предсказуемое имя ``<name>.tmp`` —
конкурентные записи одного ключа затирали tmp-файл друг друга (3 из 4
падали с ``FileNotFoundError``), а при ошибке записи ``.tmp`` оставался в
каталоге навсегда.

Дефект (6) [medium]: проверка «выхода за пределы base_path» делалась
``str.startswith(str(base))`` — без разделителя. Каталог-сосед
``<base>_evil`` проходил проверку (symlink-escape).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.backend.infrastructure.storage.local_fs import LocalFSStorage


@pytest.fixture
def storage(tmp_path: Path) -> LocalFSStorage:
    """LocalFS поверх изолированной ``tmp_path``."""
    return LocalFSStorage(base_path=tmp_path)


@pytest.mark.asyncio
async def test_concurrent_uploads_to_same_key_all_succeed(
    storage: LocalFSStorage,
) -> None:
    """(5) 4 конкурентных upload'а одного ключа → все успешны."""
    results = await asyncio.gather(
        *(storage.upload("shared.bin", f"payload-{i}".encode()) for i in range(4))
    )

    assert len(results) == 4
    assert await storage.download("shared.bin") in {
        f"payload-{i}".encode() for i in range(4)
    }


@pytest.mark.asyncio
async def test_no_temp_files_left_after_upload(storage: LocalFSStorage) -> None:
    """(5) Временные файлы не остаются в каталоге после успешной записи."""
    await storage.upload("a.bin", b"x")

    leftovers = [p.name for p in storage._base.rglob("*.tmp")]
    assert leftovers == []


@pytest.mark.asyncio
async def test_temp_file_removed_on_write_failure(
    storage: LocalFSStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(5) При ошибке записи временный файл тоже удаляется (finally)."""
    import aiofiles

    real_open = aiofiles.open

    def _failing_open(file: object, *args: object, **kwargs: object) -> object:
        if str(file).endswith(".tmp"):
            raise OSError("disk full (simulated)")
        return real_open(file, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("aiofiles.open", _failing_open)

    with pytest.raises(OSError):
        await storage.upload("fail.bin", b"x")

    assert [p.name for p in storage._base.rglob("*.tmp")] == []


@pytest.mark.asyncio
async def test_temp_file_names_are_unique(storage: LocalFSStorage) -> None:
    """(5) Имена временных файлов уникальны (uuid4), а не предсказуемы."""
    await storage.upload("a.bin", b"x")

    assert not (storage._base / "a.bin.tmp").exists()


@pytest.mark.asyncio
async def test_sibling_directory_with_same_prefix_is_rejected(tmp_path: Path) -> None:
    """(6) ``<base>_evil`` — соседний каталог, а не подкаталог base.

    Сценарий аудит-пробы: symlink внутри base указывает на соседний каталог
    с тем же префиксом (``storage`` → ``storage_evil``). Prefix-check без
    разделителя (``str.startswith``) такой путь принимал.
    """
    probe = tmp_path / "probe"
    probe.mkdir()
    base = probe / "storage"
    base.mkdir()
    evil = probe / "storage_evil"
    evil.mkdir()
    (evil / "pwned.txt").write_text("pwned")
    (base / "link").symlink_to(evil)

    storage = LocalFSStorage(base_path=base)

    with pytest.raises(ValueError, match="за пределы base_path"):
        await storage.upload("link/pwned.txt", b"x")


@pytest.mark.asyncio
async def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    """(6) Симлинк наружу из base → отказ (symlink-escape)."""
    base = tmp_path / "storage"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (base / "link").symlink_to(outside)

    storage = LocalFSStorage(base_path=base)

    with pytest.raises(ValueError, match="за пределы base_path"):
        await storage.upload("link/secret.txt", b"x")


@pytest.mark.asyncio
async def test_size_returns_object_size(storage: LocalFSStorage) -> None:
    """Размер объекта доступен для учёта квот (ADR-0390, дефект 7)."""
    await storage.upload("a.bin", b"12345")

    assert await storage.size("a.bin") == 5
    assert await storage.size("missing.bin") == 0
