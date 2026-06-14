"""Общий bootstrap для всех unit-тестов.

Решает pre-existing блокеры тестовой инфраструктуры, которые иначе пришлось
бы дублировать в каждом подкаталоге:

1. ``BaseSettingsWithLoader`` ищет ``config_profiles/`` через
   ``consts.ROOT_DIR``, а по умолчанию ``ROOT_DIR`` указывает на ``src/``.
   Подменяем на ближайший каталог-предок с ``pyproject.toml``
   (worktree-safe). Также подгружаем ``.env`` оттуда, если он есть.
2. ``LoggerManager`` (singleton при импорте ``logging_service``) пытается
   подключиться к Graylog. Через env ``LOG_HOST=""`` отключаем graylog
   handler — :meth:`GraylogHandler.enabled` возвращает False.
3. Дефолты для обязательных env-vars (REDIS_* / MAIL_* / QUEUE_* / FS_*) —
   на случай отсутствия ``.env`` в worktree-копии. ``setdefault`` уважает
   реальные значения и срабатывает только как fallback.
4. Cleanup-hook для importlib-stub pollution — некоторые тесты
   (composition/lifecycle/test_outbox_dispatcher_cutover.py,
   infrastructure/messaging/outbox/test_claim_pending.py и
   test_per_row_claim_and_sweeper.py) подменяют ``sys.modules`` пустыми
   stub'ами через ``types.ModuleType(...)``, чтобы обойти pre-existing баги
   lazy-accessor chain в project imports. После collection таких тестов
   реальные ``import`` нижестоящих тестов берут stub из ``sys.modules`` и
   падают с ``AttributeError`` или ``ImportError``. ``pytest_collectstart``
   hook, который перед collection каждого File удаляет polluted модули —
   следующий ``import`` подтянет настоящий пакет через ``__init__.py``.

Подкаталоговые ``conftest.py`` выполняются ПОСЛЕ этого файла и могут
дополнять его специфичными частями (например, security-стабы для
``cert_store`` или Python-2 syntax patcher для DSL).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

from src.backend.core.config.constants import consts


def _find_repo_root_with_config() -> Path | None:
    """Найти ближайший каталог-предок, содержащий ``pyproject.toml``.

    Anchor — ``pyproject.toml``: единственный файл, гарантированно
    лежащий в корне репозитория. Каталог ``config_profiles/`` рядом с
    ним содержит загружаемые YAML-настройки.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


# (1) ROOT_DIR -> корень репо.
_REPO_ROOT = _find_repo_root_with_config()
if _REPO_ROOT is not None:
    consts.ROOT_DIR = _REPO_ROOT
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        # Worktree без своего .env (типично для git worktree-копий). Идём
        # вверх по parents и ищем ближайший .env-файл — обычно это .env
        # основного репозитория.
        for parent in _REPO_ROOT.parents:
            candidate = parent / ".env"
            if candidate.exists():
                load_dotenv(candidate)
                break

# (2) Отключаем graylog в LoggerManager до импорта logger-модулей.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")

# (3) Безопасные fallback-дефолты для обязательных env-vars. ``setdefault``
# не перезатирает реальные значения из ``.env`` или CI-конфига.
# Redis (см. src/core/config/services/cache.py:RedisSettings).
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "0")
os.environ.setdefault("REDIS_PASSWORD", "")
# Mail (см. src/core/config/services/mail.py:MailSettings) — host/port в YAML,
# username/password — секреты.
os.environ.setdefault("MAIL_USERNAME", "")
os.environ.setdefault("MAIL_PASSWORD", "")
# Queue (см. src/core/config/services/queue.py:QueueSettings).
os.environ.setdefault("QUEUE_USERNAME", "")
os.environ.setdefault("QUEUE_PASSWORD", "")
# File-storage (см. src/core/config/services/storage.py).
os.environ.setdefault("FS_ACCESS_KEY", "")
os.environ.setdefault("FS_SECRET_KEY", "")


# (4) Cleanup hook для importlib-stub pollution (см. module docstring).
_POLLUTED_MODULE_KEYS = (
    "src.backend.plugins.composition",
    "src.backend.plugins.composition.lifecycle",
    "src.backend.plugins.composition.lifecycle.bootstrap",
    "src.backend.plugins.composition.lifecycle.protocols",
    "src.backend.plugins.composition.lifecycle.v11",
    "src.backend.plugins.composition.lifecycle.watchers",
    "src.backend.plugins.composition.lifecycle.startup",
    "src.backend.plugins.composition.lifecycle.lifespan",
    "src.backend.plugins.composition.lifecycle.shutdown",
    "src.backend.plugins.composition.lifecycle.signals",
    # S64 W1 review: outbox-тесты stub'ят session_manager чтобы обойти
    # lazy-accessor chain. Заглушка остаётся в sys.modules и ломает
    # последующие тесты, использующие main_session_manager.connection().
    "src.backend.infrastructure.database.session_manager",
    # S66 lifecycle: test_outbox_dispatcher_cutover.py stub'ит repositories.outbox
    # (line 174), чтобы обойти import-time DB connection. Заглушка остаётся
    # в sys.modules и ломает tests/unit/infrastructure/messaging/outbox/
    # тесты, которым нужен реальный ALLOWED_TRANSPORTS, claim_pending и т.п.
    "src.backend.infrastructure.repositories.outbox",
)


def _is_polluted_module(key: str) -> bool:
    """Модуль polluted, если это empty stub или fake с ``isolated`` именем.

    Detection strategies:
    1. ``__name__`` содержит ``isolated`` (importlib.util fake).
    2. ``__file__`` is None + ``__path__`` is None — оба None, так бывает
       только у stub'а из ``types.ModuleType("name")`` (real модуль всегда
       имеет хотя бы один из них).
    3. Stub-package: ``__file__`` is None + ``__path__`` not None (fake
       пакет без реального расположения на диске).
    """
    mod = sys.modules.get(key)
    if mod is None:
        return False
    fake_name = getattr(mod, "__name__", "") or ""
    if "isolated" in fake_name or fake_name.startswith("_isolated_"):
        return True
    file = getattr(mod, "__file__", None)
    path = getattr(mod, "__path__", None)
    if file is None and path is None:
        # Module stub (types.ModuleType с одним __name__).
        return True
    if file is None and path is not None:
        # Package stub: __path__ есть (fake path), но __file__ нет.
        return True
    return False


def _cleanup_polluted_modules() -> int:
    """Удаляет polluted модули из sys.modules. Возвращает кол-во удалённых."""
    removed = 0
    for k in _POLLUTED_MODULE_KEYS:
        if k in sys.modules and _is_polluted_module(k):
            del sys.modules[k]
            removed += 1
    return removed


@pytest.hookimpl(tryfirst=True)
def pytest_collectstart(collector: pytest.Collector) -> None:
    """Перед collection каждого узла — cleanup pollution от предыдущих.

    Вызываем для ВСЕХ collector-ов (включая Module, Class), потому что
    import в test_claim_pending.py выполняется на module-уровне и
    сохраняет stub в sys.modules ещё до того, как File-коллектор
    попытается собрать конкретные test-функции. После cleanup следующий
    ``import`` в test_base_repository подтянет настоящий пакет через
    ``__init__.py``.
    """
    _cleanup_polluted_modules()
