"""Local filesystem Model Registry backend.

Wave: ``[wave:s29/local-models-repository]``.

Читает модели из ``${AI_WORKSPACE}/models/`` — каталог с subfolders
по имени модели (кредитная модель → ``credit_scoring/``), каждый
содержит ``.model_manifest.json`` + бинарный файл модели (``.pt``,
``.pth``, ``.joblib``, ``.cbm``, ``.pkl``).

Lazy-import тяжёлых библиотек (torch, sklearn, catboost, lightgbm).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.backend.services.ai.model_registry.adapter import (
    ModelRecord,
    ModelRegistryAdapter,
)

if TYPE_CHECKING:
    pass

__all__ = ("LocalFSModelRegistry",)

_logger = logging.getLogger(__name__)


class LocalFSModelRegistry(ModelRegistryAdapter):
    """Backend для локального filesystem-based model registry.

    Структура каталога::

        ${AI_WORKSPACE}/models/
        ├── credit_scoring/
        │   ├── .model_manifest.json   # метаданные модели
        │   ├── v1.pt                  # бинарный файл (torch state_dict)
        │   └── v2.pt
        └── fraud_detector/
            ├── .model_manifest.json
            └── v1.joblib

    manifest JSON::

        {
          "name": "credit_scoring",
          "version": "v2",
          "framework": "torch",
          "description": "Кредитная модель v2",
          "tags": {"team": "ml", "env": "prod"},
          "artifact_uri": "...",   # заполняется при регистрации
          "stage": "Production",
          "created_at": "2026-05-28T10:00:00Z"
        }

    Args:
        workspace_path: Путь к ``${AI_WORKSPACE}`` (default из env ``AI_WORKSPACE``
            или ``/tmp/ai_workspace``). Должен содержать подкаталог ``models/``.
        models_subdir: Имя подкаталога моделей внутри workspace (default ``models``).
    """

    def __init__(
        self, *, workspace_path: str | None = None, models_subdir: str = "models"
    ) -> None:
        import os

        base = workspace_path or os.environ.get(
            # S108: AI_WORKSPACE intentionally uses temp dir as dev fallback (V15 R-V15-4)
            "AI_WORKSPACE",
            "/tmp/ai_workspace",  # noqa: S108
        )
        self._root = Path(base).expanduser().resolve() / models_subdir

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _model_dir(self, name: str) -> Path:
        """Каталог конкретной модели (без trailing slash)."""
        # S108/S301: явная валидация против path traversal
        # Категорически запрещаем любые path separator и ".."
        if ".." in name or "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"Invalid model name (path traversal attempt): {name!r}")
        target = self._root / name
        # verify traversal resolves within root
        resolved = target.resolve()
        root_resolved = self._root.resolve()
        if not str(resolved).startswith(str(root_resolved)):
            raise ValueError(f"Path traversal attempt: {name!r}")
        return target

    def _manifest_path(self, model_dir: Path) -> Path:
        return model_dir / ".model_manifest.json"

    async def _read_manifest(self, model_dir: Path) -> dict[str, Any] | None:
        """Читает manifest из каталога модели (async, через executor)."""
        path = self._manifest_path(model_dir)
        if not path.exists():
            return None
        try:
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(
                None, lambda: path.read_text(encoding="utf-8")
            )
            return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Failed to read manifest %s: %s", path, exc)
            return None

    async def _list_model_dirs(self) -> list[Path]:
        """Возвращает все подкаталоги с manifest."""
        if not self._root.exists():
            return []
        loop = asyncio.get_running_loop()
        try:
            dirs: list[Path] = await loop.run_in_executor(
                None,
                lambda: [
                    p
                    for p in self._root.iterdir()
                    if p.is_dir() and (p / ".model_manifest.json").exists()
                ],
            )
            return dirs
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Failed to list model dirs in %s: %s", self._root, exc)
            return []

    def _detect_artifact(self, model_dir: Path) -> str | None:
        """Находит бинарный файл модели в каталоге (для artifact_uri)."""
        for suffix in (".pt", ".pth", ".jit.pt", ".joblib", ".pkl", ".cbm", ".pkl.gz"):
            candidates = list(model_dir.glob(f"*{suffix}"))
            if candidates:
                # Самая свежая версия по mtime
                return str(max(candidates, key=lambda p: p.stat().st_mtime))
        return None

    # ── ModelRegistryAdapter implementation ──────────────────────────────────

    async def list_models(self) -> list[ModelRecord]:
        """Возвращает все модели из локального registry."""
        records: list[ModelRecord] = []
        for model_dir in await self._list_model_dirs():
            manifest = await self._read_manifest(model_dir)
            if manifest is None:
                continue
            artifact = self._detect_artifact(model_dir)
            try:
                record = ModelRecord(
                    name=manifest.get("name", model_dir.name),
                    version=manifest.get("version", "1"),
                    stage=manifest.get("stage", "None"),
                    artifact_uri=artifact,
                    tags=manifest.get("tags", {}),
                    description=manifest.get("description"),
                    created_at=datetime.fromisoformat(manifest["created_at"])
                    if "created_at" in manifest
                    else None,
                    extra={"backend": "local_fs", "model_dir": str(model_dir)},
                )
                records.append(record)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Malformed manifest in %s: %s", model_dir, exc)
        return records

    async def get_model(
        self, name: str, *, version: str | None = None, stage: str | None = None
    ) -> ModelRecord | None:
        """Находит модель по имени + version или stage."""
        candidates = await self.list_models()
        for rec in candidates:
            if rec.name != name:
                continue
            if version is not None and rec.version != version:
                continue
            if stage is not None and rec.stage != stage:
                continue
            return rec
        return None

    async def register_model(self, record: ModelRecord) -> ModelRecord:
        """Регистрирует модель: создаёт каталог + пишет manifest.json."""
        model_dir = self._model_dir(record.name)
        loop = asyncio.get_running_loop()

        await loop.run_in_executor(
            None, lambda: model_dir.mkdir(parents=True, exist_ok=True)
        )

        manifest: dict[str, Any] = {
            "name": record.name,
            "version": record.version,
            "framework": record.tags.get("framework", "unknown"),
            "description": record.description or "",
            "tags": record.tags,
            "stage": record.stage,
            "created_at": datetime.now().isoformat(),
        }
        manifest_path = self._manifest_path(model_dir)
        content = json.dumps(manifest, ensure_ascii=False, indent=2)
        await loop.run_in_executor(
            None, lambda: manifest_path.write_text(content, encoding="utf-8")
        )
        _logger.info(
            "Registered model %s/%s in %s", record.name, record.version, model_dir
        )
        return record.model_copy(
            update={
                "artifact_uri": str(model_dir),
                "extra": dict(record.extra) | {"backend": "local_fs"},
            }
        )

    async def transition_stage(
        self, name: str, version: str, new_stage: str
    ) -> ModelRecord:
        """Обновляет stage в manifest.json модели."""
        model_dir = self._model_dir(name)
        manifest = await self._read_manifest(model_dir)
        if manifest is None:
            raise FileNotFoundError(f"Model {name} not found in local registry")
        manifest["stage"] = new_stage
        loop = asyncio.get_running_loop()
        content = json.dumps(manifest, ensure_ascii=False, indent=2)
        manifest_path = self._manifest_path(model_dir)

        def _write_text(p: Path, c: str) -> None:
            p.write_text(c, encoding="utf-8")

        await loop.run_in_executor(None, _write_text, manifest_path, content)
        # Re-read to get full record
        return await self.get_model(name, version=version) or ModelRecord(
            name=name,
            version=version,
            stage=new_stage,  
        )
