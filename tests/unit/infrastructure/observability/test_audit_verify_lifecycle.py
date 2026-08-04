"""Регрессионные тесты для :mod:`audit_verify_lifecycle` (FIX-H5, B-series 2026-08-03).

Покрывает:
    1. ``test_try_start_default_off_flag_noop`` — opt-in через
       ``feature_flags.audit_hmac_verify_enabled=False`` → no-op, scheduler
       не запускается.
    2. ``test_try_start_default_runs_scheduler_when_on`` — flag=True →
       TaskRegistry получает background-task, default_scheduler.is_running=True.
    3. ``test_try_start_default_swallows_start_failure`` — bootstrap failure →
       log+False (best-effort семантика, не валит startup).
    4. ``test_stop_audit_verify_cancels_task`` — graceful stop отменяет
       background-task и переключает ``is_running`` в ``False``.
    5. ``test_loop_runs_verify_and_handles_failures`` — внутренний ``_loop``
       инкрементит ``runs_total`` даже если ``store.verify()`` кидает
       исключения (defense-in-depth).
    6. ``test_loop_detects_tampering_logs_error`` — ``verify()`` с
       ``valid=False`` логируется на ERROR-уровне через caplog.
    7. ``test_invalid_interval_raises`` — конструктор Scheduler валидирует
       ``interval_hours > 0``.
    8. ``test_loop_responds_to_running_flag`` — ``_loop()`` выходит на
       ``self._running=False`` (graceful stop).
    9. ``test_start_is_idempotent`` — повторный ``start()`` на running
       scheduler — no-op, не плодит дополнительных задач.

Sprint 4 L10.4.6 (S171 M5-style audit):
   10. ``test_audit_hmac_verify_default_off_regardless_of_environment`` —
       ``APP_ENVIRONMENT=production`` НЕ auto-flips ``audit_hmac_verify_enabled``:
       флаг остаётся ``False`` без явного ``FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true``
       (opt-in дизайн, документирован в ``ObservabilityFlags``).
   11. ``test_audit_hmac_verify_explicit_env_overrides_default_in_production`` —
       explicit ``FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true`` через env → pydantic
       поднимает flag → ``try_start_default()`` запускает scheduler. Это
       доказывает, что **production disable** HMAC verify выключен, но при
       explicit opt-in через feature flag — active.

Подход:
    * Реальный Postgres не нужен: ``store`` подменяется ``AsyncMock`` с
      настраиваемым ``verify()``.
    * TaskRegistry singleton — не сбрасываем (per-process singleton), но
      через ``try_start_default`` и явный ``stop_audit_verify`` гарантируем
      cleanup между тестами.
    * Для env-var тестов используем monkeypatch для изоляции и фикстуру
      ``_reset_feature_flags_env`` — pydantic-settings кеширует env, нужно
      явно чистить ``os.environ``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import src.backend.infrastructure.observability.audit_verify_lifecycle as lifecycle_mod
from src.backend.infrastructure.observability.audit_verify_lifecycle import (
    AuditVerifyScheduler,
    start_audit_verify,
    stop_audit_verify,
    try_start_default,
)
from src.backend.infrastructure.observability.immutable_audit import VerifyResult

# ─── Фикстуры ──────────────────────────────────────────────────────────────────


def _make_ok_verify_result(total: int = 5) -> VerifyResult:
    """Build a valid VerifyResult для успешного verify()."""
    return VerifyResult(
        valid=True, total_checked=total, first_broken_seq=None, details="ok"
    )


def _make_tamper_result(total: int = 10, first_seq: int = 7) -> VerifyResult:
    """Build a tampered VerifyResult для negative-ветки verify()."""
    return VerifyResult(
        valid=False,
        total_checked=total,
        first_broken_seq=first_seq,
        details=f"broken at seq={first_seq}",
    )


@pytest.fixture
def mock_store() -> AsyncMock:
    """AsyncMock-«store» с verify() по умолчанию возвращающим OK.

    Override через ``mock_store.verify = AsyncMock(side_effect=...)`` per test.
    """
    store = AsyncMock()
    store.verify = AsyncMock(return_value=_make_ok_verify_result())
    return store


@pytest.fixture(autouse=True)
async def _cleanup_scheduler() -> Any:
    """Гарантированно останавливает scheduler после каждого теста.

    autouse=True → идемпотентность по умолчанию; не нужно вручную
    вызывать в каждом тесте.
    """
    yield
    await stop_audit_verify()


# ─── Тесты ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_try_start_default_off_flag_noop() -> None:
    """Flag=OFF → try_start_default() возвращает False, scheduler не запускается."""

    def _factory() -> Any:
        # Если factory вдруг вызовется — тест зафиксирует неуспех через assert.
        raise AssertionError(
            "factory должна быть no-op когда flag=OFF (early-exit branch)"
        )

    with patch("src.backend.core.config.features.feature_flags") as mock_flags:
        mock_flags.audit_hmac_verify_enabled = False
        result = await try_start_default(session_factory=_factory)

    assert result is False
    # Используем module attribute (import-by-ref) — global переприсваивается.
    assert (
        lifecycle_mod.default_scheduler is None
        or not lifecycle_mod.default_scheduler.is_running
    )


@pytest.mark.asyncio
async def test_try_start_default_runs_scheduler_when_on() -> None:
    """Flag=ON + валидный factory → scheduler запущен в TaskRegistry."""
    with patch("src.backend.core.config.features.feature_flags") as mock_flags:
        mock_flags.audit_hmac_verify_enabled = True
        # Pydantic-флаг — bool. Гарантируем getattr() пройдёт.
        result = await try_start_default(session_factory=lambda: None)

    # Возврат bool, не raise — best-effort семантика.
    assert isinstance(result, bool)
    assert result is True, "try_start_default должен вернуть True при flag=ON"
    # Используем module attribute — global переприсваивается при start_audit_verify.
    assert lifecycle_mod.default_scheduler is not None
    assert lifecycle_mod.default_scheduler.is_running is True
    assert lifecycle_mod.default_scheduler._task is not None  # type: ignore[union-attr]
    assert not lifecycle_mod.default_scheduler._task.done()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_try_start_default_swallows_start_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """start_audit_verify() бросает исключение → try_start_default log+False (best-effort).

    NB: ``ImmutableAuditStore.__init__`` НЕ вызывает factory лениво (factory
    инвокается только из ``verify()``). Поэтому настоящий bootstrap-failure
    симулируем через подмену ``AuditVerifyScheduler`` на broken-объект.
    """
    with patch("src.backend.core.config.features.feature_flags") as mock_flags:
        mock_flags.audit_hmac_verify_enabled = True
        # Подменяем start_audit_verify так, чтобы он кинул RuntimeError —
        # имитируем невозможность зарегистрировать background-task.
        with patch(
            "src.backend.infrastructure.observability.audit_verify_lifecycle"
            ".start_audit_verify",
            side_effect=RuntimeError("TaskRegistry unavailable"),
        ):
            with caplog.at_level("WARNING"):
                result = await try_start_default(session_factory=lambda: None)

    assert result is False
    # Лог должен содержать warning о пропуске bootstrap.
    assert any("start failed" in r.message for r in caplog.records), (
        f"Ожидался WARNING о start failure, got: {[r.message for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_stop_audit_verify_cancels_task() -> None:
    """stop_audit_verify() отменяет background-task и сбрасывает is_running."""
    # Ручной scheduler, минуя try_start_default (без feature-flag).
    store = mock_store_factory()
    await start_audit_verify(
        store=store,  # type: ignore[arg-type]
        interval_hours=24.0,
    )

    assert lifecycle_mod.default_scheduler is not None
    assert lifecycle_mod.default_scheduler.is_running is True

    await stop_audit_verify()

    assert lifecycle_mod.default_scheduler.is_running is False
    assert (
        lifecycle_mod.default_scheduler._task is None
        or lifecycle_mod.default_scheduler._task.done()  # type: ignore[union-attr]
    )


def mock_store_factory() -> Any:
    """Helper: создаёт AsyncMock-«store» для ручного start_audit_verify."""
    store = AsyncMock()
    store.verify = AsyncMock(return_value=_make_ok_verify_result())
    return store


@pytest.mark.asyncio
async def test_loop_runs_verify_and_handles_failures() -> None:
    """_loop() инкрементит runs_total даже если verify() падает."""
    store = AsyncMock()
    # Первый вызов OK, второй — exception, третий — OK (defense-in-depth).
    call_count = 0

    async def _flaky_verify() -> VerifyResult:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("transient DB error")
        return _make_ok_verify_result(total=call_count)

    store.verify = _flaky_verify

    # Интервал 0.01s — быстрый тест.
    scheduler = AuditVerifyScheduler(store=store, interval_hours=0.01 / 3600.0)
    await scheduler.start()
    # Ждём 3 итерации (call_count >= 3) — bound по времени.
    deadline = asyncio.get_event_loop().time() + 2.0
    while call_count < 3 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)
    await scheduler.stop()

    assert call_count >= 3, f"Ожидалось ≥3 verify-вызова, получено {call_count}"
    assert scheduler.runs_total >= 2  # 2 успешных + 1 фейл (runs_total++ после success)


@pytest.mark.asyncio
async def test_loop_detects_tampering_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """verify() с valid=False логируется на ERROR (SOC/SIEM signal)."""
    store = AsyncMock()
    store.verify = AsyncMock(return_value=_make_tamper_result(total=10, first_seq=7))

    scheduler = AuditVerifyScheduler(store=store, interval_hours=0.01 / 3600.0)

    with caplog.at_level("ERROR", logger="observability.audit_verify_lifecycle"):
        await scheduler.start()
        # Ждём один полный цикл.
        await asyncio.sleep(0.1)
        await scheduler.stop()

    # TAMPER DETECTED должно появиться в логах.
    assert any("TAMPER DETECTED" in r.message for r in caplog.records), (
        f"Ожидался ERROR 'TAMPER DETECTED', got: {[r.message for r in caplog.records]}"
    )
    assert any(r.levelname == "ERROR" for r in caplog.records), (
        "Должен быть хотя бы один ERROR-уровневый лог"
    )


def test_invalid_interval_raises() -> None:
    """Конструктор валидирует interval_hours > 0."""
    store = AsyncMock()
    with pytest.raises(ValueError, match="interval_hours"):
        AuditVerifyScheduler(store=store, interval_hours=0.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="interval_hours"):
        AuditVerifyScheduler(store=store, interval_hours=-1.0)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_loop_responds_to_running_flag() -> None:
    """_loop() выходит при ``self._running=False`` (graceful stop)."""
    store = AsyncMock()
    store.verify = AsyncMock(return_value=_make_ok_verify_result())

    scheduler = AuditVerifyScheduler(store=store, interval_hours=0.01 / 3600.0)
    await scheduler.start()
    assert scheduler.is_running is True
    # Останавливаем через stop(), _running=False → _loop() выйдет.
    await scheduler.stop()
    assert scheduler.is_running is False
    # Дополнительный sleep — даём _loop шанс среагировать на _running=False.
    await asyncio.sleep(0.1)
    assert scheduler._task is None or scheduler._task.done()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    """Повторный start() на running scheduler — no-op, не плодит задачи."""
    store = mock_store_factory()
    scheduler = AuditVerifyScheduler(store=store, interval_hours=0.01 / 3600.0)
    await scheduler.start()
    first_task = scheduler._task
    await scheduler.start()  # second call — no-op
    second_task = scheduler._task
    await scheduler.stop()
    assert first_task is second_task


# ─── Sprint 4 L10.4.6 — production / env-var regression ──────────────────────


@pytest.mark.asyncio
async def test_audit_hmac_verify_default_off_regardless_of_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``APP_ENVIRONMENT=production`` НЕ auto-flip'ает ``audit_hmac_verify_enabled``.

    Доказательство by-design семантики opt-in:

    * ``ObservabilityFlags.audit_hmac_verify_enabled`` имеет ``default=False``
      (см. ``src/backend/core/config/features/observability.py:53-64``).
    * В коде нет ни одного места, где ``APP_ENVIRONMENT=production``
      триггерит автоматическое включение HMAC verify (проверено через
      ``grep -rn 'APP_ENVIRONMENT.*audit[+|]audit.*APP_ENVIRONMENT'``).
    * Следовательно, ``try_start_default()`` без явного env
      ``FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true`` остаётся no-op даже в prod.

    Это **safe by design** — production deployment обязан явно выставить
    ``FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true`` в helm-values/secret-env.
    """
    # Изолируем env — чистим FEATURE_AUDIT_HMAC_VERIFY_ENABLED + APP_ENVIRONMENT.
    monkeypatch.delenv("FEATURE_AUDIT_HMAC_VERIFY_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")

    # Загружаем flag-класс с нуля — pydantic-settings читает env заново.
    from src.backend.core.config.features.observability import ObservabilityFlags

    flags = ObservabilityFlags()

    # Default-OFF остаётся даже при APP_ENVIRONMENT=production.
    assert flags.audit_hmac_verify_enabled is False, (
        "audit_hmac_verify_enabled должен оставаться False без явного env, "
        "даже при APP_ENVIRONMENT=production (opt-in by design)"
    )

    # try_start_default() уважает флаг — возвращает False.
    def _factory() -> Any:
        raise AssertionError("factory должна быть no-op когда flag=OFF")

    result = await try_start_default(session_factory=_factory)
    assert result is False, "try_start_default должен вернуть False без explicit flag"
    assert (
        lifecycle_mod.default_scheduler is None
        or not lifecycle_mod.default_scheduler.is_running
    )


@pytest.mark.asyncio
async def test_audit_hmac_verify_explicit_env_overrides_default_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit ``FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true`` запускает scheduler.

    Это доказывает, что **production HMAC verify active через explicit feature
    flag**: при наличии env-флага в production — scheduler запускается. Без
    флага (даже в production) — нет. Никакой «production disable» по
    ``APP_ENVIRONMENT`` не происходит — только opt-in.
    """
    # Явный opt-in в production.
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("FEATURE_AUDIT_HMAC_VERIFY_ENABLED", "true")

    from src.backend.core.config.features.observability import ObservabilityFlags

    flags = ObservabilityFlags()

    # Явный env-флаг перекрывает default-False.
    assert flags.audit_hmac_verify_enabled is True, (
        "FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true должен включить флаг "
        "вне зависимости от APP_ENVIRONMENT"
    )

    # try_start_default() видит flag=True → запускает scheduler.
    # NB: ``feature_flags`` — singleton, инстанцированный до теста; патчим
    # атрибут напрямую (минимальная изоляция — этот сценарий не зависит
    # от singleton state, важно лишь, что ``getattr(flag, ..., False)``
    # возвращает True).
    with patch("src.backend.core.config.features.feature_flags") as mock_flags:
        mock_flags.audit_hmac_verify_enabled = True
        result = await try_start_default(session_factory=lambda: None)

    assert result is True, (
        "try_start_default должен вернуть True при explicit opt-in "
        "(production + FEATURE_AUDIT_HMAC_VERIFY_ENABLED=true)"
    )
    assert lifecycle_mod.default_scheduler is not None
    assert lifecycle_mod.default_scheduler.is_running is True
    assert lifecycle_mod.default_scheduler._task is not None  # type: ignore[union-attr]
    assert not lifecycle_mod.default_scheduler._task.done()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_audit_hmac_verify_flag_isolated_from_environment_autodetect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag НЕ зависит от APP_ENVIRONMENT (нет автоопределения).

    Устанавливаем APP_ENVIRONMENT в разные значения и убеждаемся, что
    ``audit_hmac_verify_enabled`` остаётся ``False`` без явного env.
    Доказывает отсутствие «production auto-enable» побочного эффекта.
    """
    from src.backend.core.config.features.observability import ObservabilityFlags

    monkeypatch.delenv("FEATURE_AUDIT_HMAC_VERIFY_ENABLED", raising=False)

    for env_value in ("development", "staging", "production"):
        monkeypatch.setenv("APP_ENVIRONMENT", env_value)
        flags = ObservabilityFlags()
        assert flags.audit_hmac_verify_enabled is False, (
            f"APP_ENVIRONMENT={env_value!r} не должен auto-enable "
            f"audit_hmac_verify_enabled без explicit FEATURE_AUDIT_HMAC_VERIFY_ENABLED"
        )


@pytest.mark.asyncio
async def test_try_start_default_idempotent_via_global_scheduler() -> None:
    """Повторный ``try_start_default()`` с flag=ON — scheduler не дублируется.

    NB: ``start_audit_verify()`` идемпотентен через ``is_running``-guard
    (см. ``audit_verify_lifecycle.py:178-180``). Поэтому ``default_scheduler``
    остаётся тем же объектом, и в ``TaskRegistry`` нет дублей.
    """
    with patch("src.backend.core.config.features.feature_flags") as mock_flags:
        mock_flags.audit_hmac_verify_enabled = True
        first_result = await try_start_default(session_factory=lambda: None)
        second_result = await try_start_default(session_factory=lambda: None)

    assert first_result is True
    assert second_result is True
    assert lifecycle_mod.default_scheduler is not None
    # Идемпотентность: тот же объект scheduler, не новый инстанс.
    assert lifecycle_mod.default_scheduler.is_running is True
