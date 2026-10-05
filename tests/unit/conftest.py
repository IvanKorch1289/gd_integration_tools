"""Общий bootstrap для всех unit-тестов.

Решает pre-existing блокеры тестовой инфраструктуры, которые иначе пришлось
бы дублировать в каждом подкаталоге:

1. ``BaseSettingsWithLoader`` ищет ``config_profiles/`` через
   ``consts.ROOT_DIR``, а по умолчанию ``ROOT_DIR`` указывает на ``src/``.
   Подменяем на ближайший каталог-предок с ``pyproject.toml``
   (worktree-safe).
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

# (2) Отключаем graylog в LoggerManager до импорта logger-модулей.
os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")

# (3) Безопасные fallback-дефолты для обязательных env-vars. ``setdefault``
# не перезатирает реальные значения из CI-конфига.
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
# M8: per-test isolation via ``monkeypatch.setitem`` НЕ применяется — module-level
# ``os.environ.setdefault`` достаточно для unit-tests: env process-wide, между
# pytest-сессиями pytest-fork или subprocess-isolation перезапускают интерпретатор.
# ``monkeypatch.setitem`` создаст риск regression (тесты, полагающиеся на
# наследование env через setdefault, получат неожиданный cleanup).
_POLLUTED_MODULE_KEYS = (
    "src.backend.plugins.composition",
    "src.backend.plugins.composition.lifecycle",
    "src.backend.plugins.composition.lifecycle.bootstrap",
    "src.backend.plugins.composition.lifecycle.protocols",
    "src.backend.plugins.composition.lifecycle.plugin_loader",
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
    # Фронтенд-тесты подменяют сторонние пакеты голыми
    # ``types.ModuleType`` на уровне модуля теста (например
    # tests/unit/frontend/streamlit_app/test_91_operational_costs_imports.py
    # делает ``sys.modules["polars"] = ModuleType("polars")``) и не восстанавливают
    # их. Два изолированных следствия, оба доказаны прогоном:
    #
    #   1. ``polars`` — опциональный extra «dataframes», в дефолтной
    #      установке его нет. Подмена делает ``pytest.importorskip("polars")``
    #      бесполезным: модуль найден в sys.modules, поэтому guard срабатывает
    #      «успешно» и тест идёт против MagicMock. Проверено:
    #      ``test_converters.py::TestConversionStrategies::test_dict_to_csv``
    #      сам по себе → SKIPPED, но сразу после test_91_operational_costs_imports
    #      → FAILED («'name,age' in <MagicMock … write_csv()>»).
    #   2. ``streamlit`` установлен реально (1.63.0), но 7 фронтенд-тестов
    #      подменяют его пустым модулем, из-за чего ``import streamlit.emojis``
    #      в других сьютах падает с «'streamlit' is not a package».
    "polars",
    "streamlit",
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


# ── DI overrides: snapshot/restore после каждого теста (fix 2026-09-24) ──
# Cache/privacy-тесты пишут ``providers.cache._overrides["redis_client"] = mock``
# напрямую; без cleanup мок утекает в следующие suite'ы ("MagicMock can't be
# awaited" в grpc/mcp/eip при combined-прогоне). Snapshot/restore сохраняет
# и намеренные session-scope override'ы, и изоляцию.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _restore_di_overrides():
    from src.backend.core.di.providers import ai as _ai
    from src.backend.core.di.providers import cache as _cache
    from src.backend.core.di.providers import http as _http
    from src.backend.core.di.providers import storage as _storage
    from src.backend.core.di.providers import workflow as _workflow

    modules = (_cache, _ai, _http, _storage, _workflow)
    snapshot: dict[int, dict] = {}
    for m in modules:
        ov = getattr(m, "_overrides", None)
        if isinstance(ov, dict):
            snapshot[id(ov)] = dict(ov)
    yield
    for m in modules:
        ov = getattr(m, "_overrides", None)
        if isinstance(ov, dict) and id(ov) in snapshot:
            ov.clear()
            ov.update(snapshot[id(ov)])


# ── Tenant ContextVar: сброс после каждого теста (P1 test isolation) ──
# core.tenancy._current — общепроцессный ContextVar. Многие тесты вызывают
# set_tenant() напрямую и не отвязывают контекст, из-за чего tenant предыдущего
# теста протекает в следующий. Воспроизведено детектором:
#   tests/unit/core/security/test_reaudit_n1_n3_n4.py оставляет tenant='tenant-a',
#   и любой следующий тест в том же процессе видит чужой tenant.
# Особенно опасно для security-модулей: подмена tenant'а меняет исход проверки.
@_pytest.fixture(autouse=True)
def _reset_tenant_context():
    """Сбрасывает tenant-контекст до и после каждого теста.

    Yields:
        None: фикстура только управляет состоянием.

    """
    from src.backend.core import tenancy as _tenancy

    # ContextVar объявлен в пакете tenancy, а не в модуле sqlalchemy_filter.
    # Сбрасываем напрямую: set(None) + reset(token) эквивалентен очистке, но
    # сохраняет корректную семантику ContextVar (reset обязан идёт тем же var).
    _tenancy._current.set(None)
    yield
    _tenancy._current.set(None)
    assert _tenancy.get_tenant_id() == "", "фикстура сброса tenant не сработала"


# ── Workflow registry: cleanup после каждого теста (fix test pollution) ──
# test_emitter/test_registry мутируют singleton workflow_registry._classes,
# что утекает в последующие suite'ы (emitter → Temporal interceptor → privacy).
@_pytest.fixture(autouse=True)
def _restore_workflow_registry():
    from src.backend.core.workflow_registry import workflow_registry as _wr

    snapshot = dict(_wr._classes)
    yield
    _wr._classes.clear()
    _wr._classes.update(snapshot)


# ── sys.modules-подмены: cleanup до и после КАЖДОГО теста ──
# Хук ``pytest_collectstart`` выше ловит только загрязнение, возникшее на
# этапе collection. Но pytest собирает ВСЕ модули до запуска первого теста,
# а часть фронтенд-тестов ставит моки прямо во время выполнения
# (``_load_page_module()`` в test_91_operational_costs_imports.py). Такие
# моки переживают collection и достаются следующим сьютам уже на этапе run:
# без этого фикстуры polars-мок из фронтенд-теста ломал
# ``importorskip("polars")`` в dsl-тестах, и они падали вместо skip.
@_pytest.fixture(autouse=True)
def _purge_polluted_modules():
    _cleanup_polluted_modules()
    yield
    _cleanup_polluted_modules()


# ── TaskRegistry: снятие «закрыт» после каждого теста (fix test pollution) ──
# ``TaskRegistry.shutdown_all()`` выставляет ``_closed = True`` НАВСЕГДА, а
# ``get_task_registry()`` возвращает тот же синглтон. В проде это корректно:
# shutdown зовётся только на выходе процесса
# (plugins/composition/lifecycle/shutdown.py:245), и новых задач после него
# быть не должно — fail-closed.
#
# В тестах тот же вызов (lifespan/app-shutdown) навсегда оставлял глобал
# закрытым для всего процесса, и каждый последующий ``create_task`` падал с
# «TaskRegistry уже закрыт» — каскадом 31 падения в whole-tree прогоне.
# Восстановление выполняет уже существующий публичный метод
# ``reset_for_tests()``; новый API в продукт не добавлялся.
@_pytest.fixture(autouse=True)
def _restore_task_registry():
    from src.backend.core.utils.task_registry import get_task_registry as _get_reg

    yield
    _get_reg().reset_for_tests()
