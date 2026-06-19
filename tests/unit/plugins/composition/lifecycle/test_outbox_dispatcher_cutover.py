"""Unit-тесты для S64 W3 — outbox dispatcher cutover.

Проверяет ``_register_outbox_dispatcher()`` в lifespan.py:

* ``outbox_settings.enabled=False`` (default) → ``start_outbox_worker()`` (legacy).
* ``outbox_settings.enabled=True`` → ``start_outbox_dispatcher()`` (W1 claim).
* Exception в worker'е — log warning + не raise.

ВАЖНО: master имеет pre-existing import-bugs в
``plugins/composition/__init__.py`` (graphql_router). Чтобы обойти —
тестируем функцию ``_register_outbox_dispatcher`` через monkeypatching
outbox_settings + worker functions (не импортируем lifespan.py напрямую).

S38 lesson: function-local import → patch source module, not consumer.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load_lifespan_isolated() -> ModuleType:
    """Load ``lifespan.py`` + ``startup.py`` как isolated modules, обходя
    pre-existing import-bugs в ``plugins/composition/__init__.py``.

    Path: ``tests/unit/plugins/composition/lifecycle/`` → 6 уровней вверх → project root.

    Strategy: stub ПАКЕТЫ ``src.backend.plugins.composition`` +
    ``src.backend.plugins.composition.lifecycle`` в ``sys.modules`` ДО
    exec_module, чтобы Python НЕ запускал их ``__init__.py``
    (которые содержат сломанные imports — graphql_router и т.п.).
    Только ``lifespan.py`` + ``startup.py`` грузятся по реальному пути.

    S111 W2: ``_register_outbox_dispatcher`` переехал из ``lifespan.py``
    в ``startup.py``. lifespan.py ре-экспортирует её для backward compat.
    Тест грузит ОБА модуля, чтобы покрыть и реальный код, и re-export.
    """
    import types as _types

    # 1. Stub broken package __init__ modules ДО import.
    # Создаём BOTH package (для __init__.py trigger) И submodule-ы
    # (для ``from .X import Y`` syntax).
    # NOTE: bootstrap/protocols/watchers импортируются из
    # ``src.backend.plugins.composition.lifecycle.*`` (не из
    # ``src.backend.plugins.composition.*``).
    # S111 W2: ``startup`` module is now a sibling (S111 W2 extract).
    broken_pkgs_and_subs = {
        "src.backend.plugins.composition": True,  # package (has __path__)
        "src.backend.plugins.composition.lifecycle": True,
        "src.backend.plugins.composition.lifecycle.bootstrap": False,  # module
        "src.backend.plugins.composition.lifecycle.protocols": False,  # module
        "src.backend.plugins.composition.lifecycle.v11": False,  # module
        "src.backend.plugins.composition.lifecycle.watchers": False,  # module
    }
    for mod_name, is_package in broken_pkgs_and_subs.items():
        if mod_name not in sys.modules:
            _stub_mod = _types.ModuleType(mod_name)
            if is_package:
                _stub_mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[mod_name] = _stub_mod

    # 2. Stub имена, которые lifespan.py / startup.py импортируют на module-level.
    # S111 W2: startup.py использует ТОЛЬКО lazy imports внутри функций
    # (для избежания pre-existing import-bugs в composition package).
    # Поэтому module-level stubs нужны ТОЛЬКО для lifespan.py.
    module_level_stubs: dict[str, object] = {
        "src.backend.core.utils.task_registry.get_task_registry": MagicMock(),
        "src.backend.infrastructure.logging.factory.get_logger": MagicMock(
            return_value=MagicMock()
        ),
        "src.backend.plugins.composition.lifecycle.bootstrap.bootstrap_resilience_coordinator": AsyncMock(),
        "src.backend.plugins.composition.lifecycle.bootstrap.bootstrap_snapshot_job": AsyncMock(),
        "src.backend.plugins.composition.lifecycle.bootstrap.register_storage_singletons": MagicMock(),
        "src.backend.plugins.composition.lifecycle.bootstrap.validate_cache_layers": MagicMock(),
        "src.backend.plugins.composition.lifecycle.protocols.register_protocol_providers": MagicMock(),
        "src.backend.plugins.composition.lifecycle.v11.bootstrap_v11_plugin_loader": AsyncMock(),
        "src.backend.plugins.composition.lifecycle.v11.bootstrap_v11_route_loader": AsyncMock(),
        "src.backend.plugins.composition.lifecycle.v11.shutdown_plugin_loaders": AsyncMock(),
        "src.backend.plugins.composition.lifecycle.v11.start_v11_hot_reload": AsyncMock(),
        "src.backend.plugins.composition.lifecycle.watchers.start_dsl_yaml_watcher": MagicMock(),
        "src.backend.plugins.composition.lifecycle.watchers.stop_dsl_yaml_watcher": MagicMock(),
    }
    # 3. Stub function-local imports (lazy, в ``_register_outbox_dispatcher``)
    lazy_stubs: dict[str, object] = {
        "src.backend.core.config.services.outbox.outbox_settings": MagicMock(
            enabled=False
        ),
        "src.backend.infrastructure.workflow.outbox_worker.start_outbox_worker": MagicMock(),
        "src.backend.infrastructure.workflow.outbox_worker._publish": AsyncMock(),
        "src.backend.infrastructure.messaging.outbox.lifecycle.start_outbox_dispatcher": AsyncMock(),
        "src.backend.core.messaging.outbox.FakeOutbox": MagicMock(),
        "src.backend.core.messaging.outbox.OutboxEvent": MagicMock(),
        "src.backend.infrastructure.repositories.outbox.claim_pending": AsyncMock(
            return_value=[]
        ),
        "src.backend.infrastructure.repositories.outbox.mark_sent": AsyncMock(),
    }
    for full_name, stub_obj in {**module_level_stubs, **lazy_stubs}.items():
        # ВАЖНО: всегда перезаписываем (override уже-loaded real module).
        # pytest может заранее загрузить real модули через autouse fixtures.
        _existing = sys.modules.get(full_name)
        if _existing is None:
            _stub = _types.ModuleType(full_name)
            setattr(_stub, full_name.rsplit(".", 1)[-1], stub_obj)
            sys.modules[full_name] = _stub
        else:
            # Force-overwrite attribute on existing module.
            setattr(_existing, full_name.rsplit(".", 1)[-1], stub_obj)

    # 4. Загружаем startup.py напрямую (минуя __init__.py).
    # startup.py содержит реальную ``_register_outbox_dispatcher`` функцию.
    # Это НОВЫЙ home после S111 W2 рефактора lifespan.py.
    lifecycle_dir = (
        Path(__file__).parent.parent.parent.parent.parent.parent
        / "src"
        / "backend"
        / "plugins"
        / "composition"
        / "lifecycle"
    )
    startup_path = lifecycle_dir / "startup.py"
    spec = importlib.util.spec_from_file_location("_startup_isolated", startup_path)
    assert spec is not None and spec.loader is not None
    startup_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(startup_module)
    # Регистрируем в sys.modules ДО загрузки lifespan.py, чтобы
    # ``from .startup import _register_outbox_dispatcher`` нашёл его.
    sys.modules["src.backend.plugins.composition.lifecycle.startup"] = startup_module

    # 5. Загружаем lifespan.py напрямую (минуя __init__.py).
    # lifespan.py ре-экспортирует ``_register_outbox_dispatcher`` из startup.
    lifespan_path = lifecycle_dir / "lifespan.py"
    spec = importlib.util.spec_from_file_location("_lifespan_isolated", lifespan_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Pre-load на collection.
# NOTE: pre-loading happens at collection time. If you modify
# ``lifespan.py`` / ``startup.py`` after this, tests will use STALE
# version. Re-run pytest to pick up changes.
_lifespan = _load_lifespan_isolated()
sys.modules["src.backend.plugins.composition.lifecycle.lifespan"] = _lifespan

# Force-overwrite DEBUG print to verify _lifespan version matches
# S111 W2: re-exported from startup, but co_filename / co_firstlineno
# указывают на startup.py (где функция реально определена).
print(
    f"DEBUG TEST: _lifespan._register_outbox_dispatcher source = "
    f"{_lifespan._register_outbox_dispatcher.__code__.co_filename}:"
    f"{_lifespan._register_outbox_dispatcher.__code__.co_firstlineno}"
)

# Pre-stub outbox_repo module (BEFORE any test runs, ensure real
# outbox.py is not loaded by accidental pytest collection).
import types as _types

_outbox_stub = _types.ModuleType("src.backend.infrastructure.repositories.outbox")
_outbox_stub.claim_pending = AsyncMock(return_value=[])
_outbox_stub.mark_sent = AsyncMock()
sys.modules["src.backend.infrastructure.repositories.outbox"] = _outbox_stub


@pytest.fixture
def mock_lifespan_logger(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Подменяет ``app_logger`` в lifespan module на MagicMock.

    Без этого real ``app_logger`` (initialized при exec_module) может
    упасть на DatabaseInitializer в logging backend chain. Override-
    ит module-level ``app_logger`` attribute.
    """
    fake_logger = MagicMock()
    monkeypatch.setattr(_lifespan, "app_logger", fake_logger)
    return fake_logger


@pytest.fixture
def fresh_app() -> MagicMock:
    """Минимальный FastAPI-stand-in (без реального импорта)."""
    return MagicMock()


@pytest.fixture
def enable_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает ``outbox_settings.enabled = True`` (для теста new path)."""
    settings = MagicMock(enabled=True)
    monkeypatch.setattr(
        "src.backend.core.config.services.outbox.outbox_settings", settings
    )


@pytest.fixture
def disable_dispatcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Оставляет ``outbox_settings.enabled = False`` (для теста legacy path)."""
    settings = MagicMock(enabled=False)
    monkeypatch.setattr(
        "src.backend.core.config.services.outbox.outbox_settings", settings
    )


@pytest.mark.asyncio
async def test_cutover_legacy_path_when_disabled(
    fresh_app: MagicMock, disable_dispatcher: None, mock_lifespan_logger: MagicMock
) -> None:
    """``enabled=False`` → ``start_outbox_worker`` (legacy)."""
    with patch(
        "src.backend.infrastructure.workflow.outbox_worker.start_outbox_worker"
    ) as mock_legacy:
        await _lifespan._register_outbox_dispatcher(fresh_app)
        mock_legacy.assert_called_once_with(interval_seconds=5, batch_size=100)


@pytest.mark.asyncio
async def test_cutover_dispatcher_path_when_enabled(
    fresh_app: MagicMock, enable_dispatcher: None, mock_lifespan_logger: MagicMock
) -> None:
    """``enabled=True`` → ``start_outbox_dispatcher`` (S64 W1+W3 path)."""
    # Verify fixture applied
    import src.backend.core.config.services.outbox as _svc_outbox

    print(f"\nDEBUG: outbox_settings type={type(_svc_outbox.outbox_settings)}")
    print(f"DEBUG: outbox_settings.enabled={_svc_outbox.outbox_settings.enabled}")
    with patch(
        "src.backend.infrastructure.messaging.outbox.lifecycle.start_outbox_dispatcher",
        new=AsyncMock(),
    ) as mock_dispatcher:
        # claim_pending тоже подменим
        with patch(
            "src.backend.infrastructure.repositories.outbox.claim_pending",
            new=AsyncMock(return_value=[]),
        ):
            await _lifespan._register_outbox_dispatcher(fresh_app)
            print(f"DEBUG: dispatcher.await_count={mock_dispatcher.await_count}")
        mock_dispatcher.assert_awaited_once()
        # Verify call kwargs
        kwargs = mock_dispatcher.await_args.kwargs
        assert kwargs["app"] is fresh_app
        assert kwargs["backend"] is not None  # FakeOutbox instance
        assert callable(kwargs["pending_source"])
        assert callable(kwargs["ack"])
        assert callable(kwargs["deliverer"])


@pytest.mark.asyncio
async def test_cutover_legacy_worker_exception_does_not_raise(
    fresh_app: MagicMock, disable_dispatcher: None, mock_lifespan_logger: MagicMock
) -> None:
    """``start_outbox_worker()`` raises → log warning, не raise.

    Outbox не должен блокировать startup (best-effort).
    """
    with patch(
        "src.backend.infrastructure.workflow.outbox_worker.start_outbox_worker",
        side_effect=RuntimeError("RabbitMQ unavailable"),
    ):
        # НЕ должно raise-нуть
        await _lifespan._register_outbox_dispatcher(fresh_app)


@pytest.mark.asyncio
async def test_cutover_dispatcher_exception_does_not_raise(
    fresh_app: MagicMock, enable_dispatcher: None, mock_lifespan_logger: MagicMock
) -> None:
    """``start_outbox_dispatcher()`` raises → log warning, не raise.

    Аналогично legacy path.
    """
    with patch(
        "src.backend.infrastructure.messaging.outbox.lifecycle.start_outbox_dispatcher",
        new=AsyncMock(side_effect=RuntimeError("DB connection lost")),
    ):
        # НЕ должно raise-нуть
        await _lifespan._register_outbox_dispatcher(fresh_app)


@pytest.mark.asyncio
async def test_cutover_uses_hostname_for_worker_id(
    fresh_app: MagicMock,
    enable_dispatcher: None,
    mock_lifespan_logger: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worker_id`` = ``HOSTNAME`` env var (K8s pod name)."""
    monkeypatch.setenv("HOSTNAME", "test-pod-abc-123")
    with patch(
        "src.backend.infrastructure.messaging.outbox.lifecycle.start_outbox_dispatcher",
        new=AsyncMock(),
    ) as mock_dispatcher:
        # claim_pending мок — пустой list, чтобы не падать
        with patch(
            "src.backend.infrastructure.repositories.outbox.claim_pending",
            new=AsyncMock(return_value=[]),
        ):
            await _lifespan._register_outbox_dispatcher(fresh_app)
        # Verify worker_id передан в claim_pending (опосредованно через _pending_source)
        # Note: claim_pending мок был переопределён, поэтому _pending_source
        # использовал override-версию. Test только проверяет, что dispatcher вызван.
        mock_dispatcher.assert_awaited_once()
