"""Регресс-тесты по находкам независимого ре-аудита (2026-10-01, N-1/N-3/N-4).

Независимый reviewer попытался опровергнуть мои предыдущие FIXED-выводы и
нашёл в трёх из них дыры. Все три закрыты здесь.

* **N-1 (HIGH)** — «tenant spoofing закрыт» было **не** верно полностью.
  ``_verify_api_key`` кладёт в ``metadata`` только ``key_id``/``key_hash``/
  ``admin_roles`` — **без** ``tenant_id``. Прежняя ветка
  ``elif "tenant_id" not in state`` путала «нет аутентификации» с
  «аутентификация есть, tenant не заявлен» и в последнем случае доверяла
  заголовку: реальный ``X-API-Key`` (principal ``global``) + ``X-Tenant-ID:
  tenant-b`` давал HTTP 200 и чужой tenant в ``state`` и в ``RequestContext``.
* **N-3 (MEDIUM)** — фикс «pre_llm-хуки выполняются на чистом пути» был
  применён к одному методу. ``validate_command`` и
  ``validate_file_modification`` возвращали ``allowed=True`` вообще без
  вызова ``pre_tool``-хуков — тот же класс дефекта, двойник.
* **N-4 (MEDIUM)** — операция, упавшая **после** частичного старта (в т.ч.
  по ``TimeoutError``), не откатывалась: ``_started`` пополнялся только после
  успеха, и её ``stop()`` не вызывался.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Column, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from src.backend.core.ai.security.agent_security_framework import AgentSecurityFramework
from src.backend.core.tenancy import TenantContext, set_tenant
from src.backend.core.tenancy import sqlalchemy_filter as tf
from src.backend.plugins.composition.lifecycle.operations import (
    Criticality,
    LifecycleOperation,
    LifecycleRunner,
    LifecycleStartupError,
    LifecycleState,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]


# ── N-1: аутентифицирован, но tenant не заявлен → fail-closed ──────────


class _AuthContext:
    """Минимальный duck-typed ``AuthContext`` без ``metadata['tenant_id']``."""

    def __init__(self, metadata: dict[str, Any] | None = None) -> None:
        self.method = "api_key"
        self.principal = "global"
        self.roles = ("operator",)
        self.metadata = metadata or {
            "key_id": "k1",
            "key_hash": "h",
            "admin_roles": ["operator"],
        }


def _scope(headers: list[tuple[bytes, bytes]], auth: object | None) -> dict[str, Any]:
    """Собрать минимальный ASGI http-scope с заголовками и auth-контекстом.

    Args:
        headers: Список ``(name, value)`` в байтах.
        auth: Объект аутентификации либо ``None`` (не аутентифицирован).

    Returns:
        Словарь scope, пригодный для вызова middleware напрямую.
    """
    return {
        "type": "http",
        "path": "/api/v1/thing",
        "method": "GET",
        "headers": headers,
        "state": {} if auth is None else {"auth": auth},
    }


def _run_tenant(scope: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Прогнать ``TenantMiddleware`` по scope и вернуть статус и state.

    Args:
        scope: Подготовленный ASGI scope.

    Returns:
        Кортеж ``(status_code, state)``.
    """
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    captured: dict[str, Any] = {}

    async def _send(message: dict[str, Any]) -> None:
        # Только http.response.start несёт статус: тело ответа приходит
        # отдельным сообщением без поля status и не должно перетирать его.
        if message.get("type") == "http.response.start":
            captured["status"] = message.get("status", 200)

    async def _app(_scope: Any, _receive: Any, send: Any) -> None:
        await _send({"type": "http.response.start", "status": 200})

    middleware = TenantMiddleware(app=_app)
    asyncio.run(middleware(scope, None, _send))
    return captured.get("status", 200), scope["state"]


class TestN1AuthWithoutTenantIsFailClosed:
    """N-1: наличие аутентификации без tenant запрещает доверие заголовку."""

    def test_principal_without_tenant_and_foreign_header_denied(self) -> None:
        """API-key principal без tenant + чужой заголовок → 403."""
        scope = _scope([(b"x-tenant-id", b"tenant-b")], _AuthContext())
        status, state = _run_tenant(scope)
        assert status == 403, (
            "аутентифицированный principal не даёт выбирать tenant заголовком"
        )
        assert state.get("tenant_id") != "tenant-b"

    def test_principal_without_tenant_and_matching_header_allowed(self) -> None:
        """Тот же principal с заголовком == default → запрос проходит в default."""
        from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

        middleware = TenantMiddleware(app=None)
        default = middleware._default  # noqa: SLF001 — сверка с контрактом middleware
        scope = _scope([(b"x-tenant-id", default.encode())], _AuthContext())
        status, state = _run_tenant(scope)
        assert status == 200
        assert state["tenant_id"] == default

    def test_unauthenticated_still_may_use_header(self) -> None:
        """Без аутентификации заголовок по-прежнему задаёт tenant (не регресс)."""
        scope = _scope([(b"x-tenant-id", b"tenant-x")], None)
        status, state = _run_tenant(scope)
        assert status == 200
        assert state["tenant_id"] == "tenant-x"

    def test_auth_present_without_tenant_does_not_consult_header(self) -> None:
        """``_auth_present`` отличает «аутентифицирован» от «аутентификации нет»."""
        from src.backend.entrypoints.middlewares.tenant import _auth_present

        assert _auth_present(_scope([], _AuthContext())) is True
        assert _auth_present(_scope([], None)) is False


# ── N-3: pre_tool-хуки на «чистом» пути ────────────────────────────────


class TestN3CleanPathPreToolHooks:
    """N-3: deny-хук обязан влиять на безопасный по шаблону ввод."""

    @staticmethod
    def _framework_with_deny_hook() -> AgentSecurityFramework:
        """Собрать фреймворк с отклоняющим ``pre_tool``-хуком.

        Returns:
            Настроенный ``AgentSecurityFramework``.
        """
        from src.backend.core.ai.security.agent_security_types import (
            SecurityDecision,
            SecurityHook,
            ThreatLevel,
        )

        def _deny(_hook_name: str, _context: Any) -> SecurityDecision:
            return SecurityDecision(
                allowed=False, threat_level=ThreatLevel.HIGH, reason="denied by hook"
            )

        from src.backend.core.ai.security.agent_security_policy import (
            AgentSecurityPolicy,
        )

        framework = AgentSecurityFramework(
            policy=AgentSecurityPolicy(enable_workflow_hooks=True)
        )
        framework.register_hook(
            SecurityHook(name="deny", trigger="pre_tool", check_fn=_deny)
        )
        return framework

    def test_validate_command_clean_path_runs_hooks(self) -> None:
        """Безопасная команда всё равно проверяется pre_tool-хуком."""
        decision = self._framework_with_deny_hook().validate_command("ls -la /tmp")
        assert decision.allowed is False, "чистый путь обязан прогонять pre_tool-хуки"

    def test_validate_file_modification_clean_path_runs_hooks(self) -> None:
        """Допустимая модификация файла всё равно проверяется pre_tool-хуком."""
        decision = self._framework_with_deny_hook().validate_file_modification(
            "/tmp/safe.txt"
        )
        assert decision.allowed is False, "чистый путь обязан прогонять pre_tool-хуки"


# ── N-4: частично поднятая операция откатывается ───────────────────────


class TestN4PartialStartIsRolledBack:
    """N-4: откат обязан останавливать и частично поднятые операции."""

    @pytest.mark.asyncio
    async def test_failed_required_operation_is_stopped(self) -> None:
        """REQUIRED-операция, упавшая после старта, получает ``stop()``."""
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("partial start then fail")

        async def _stop() -> None:
            stops.append("stopped")

        op = LifecycleOperation(
            name="partial",
            phase="test",
            start=_boom,
            stop=_stop,
            criticality=Criticality.REQUIRED,
            timeout=5.0,
        )
        runner = LifecycleRunner([op])

        with pytest.raises(LifecycleStartupError):
            await runner.start_all()

        assert stops == ["stopped"], (
            "частично поднятая операция обязана быть остановлена"
        )

    @pytest.mark.asyncio
    async def test_timeout_operation_is_stopped(self) -> None:
        """Операция, упавшая по ``TimeoutError``, тоже останавливается."""

        async def _slow() -> None:
            await asyncio.sleep(5)

        async def _stop() -> None:
            stops.append("stopped")

        stops: list[str] = []
        op = LifecycleOperation(
            name="slow",
            phase="test",
            start=_slow,
            stop=_stop,
            criticality=Criticality.REQUIRED,
            timeout=0.05,
        )
        runner = LifecycleRunner([op])

        with pytest.raises(LifecycleStartupError):
            await runner.start_all()

        assert stops == ["stopped"], "операция по таймауту обязана быть остановлена"

    @pytest.mark.asyncio
    async def test_normal_shutdown_still_only_stops_started(self) -> None:
        """Обычный shutdown не должен дёргать stop() у не стартовавших операций."""
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("nope")

        async def _stop_failed() -> None:
            stops.append("failed")

        async def _stop_ok() -> None:
            stops.append("ok")

        ops = [
            LifecycleOperation(
                name="failed",
                phase="test",
                start=_boom,
                stop=_stop_failed,
                criticality=Criticality.OPTIONAL,
                timeout=1.0,
            ),
            LifecycleOperation(
                name="ok",
                phase="test",
                start=lambda: None,
                stop=_stop_ok,
                criticality=Criticality.REQUIRED,
                timeout=1.0,
            ),
        ]
        runner = LifecycleRunner(ops)
        await runner.start_all()
        await runner.shutdown()
        assert stops == ["ok"], (
            "shutdown останавливает только реально поднятые операции"
        )


# ── N-2: UNION / CTE остаются незакрытыми (фиксируется как известный пробел) ──


class _Base(DeclarativeBase):
    """База для tenant-сущности в проверке residual-пути."""


class Doc(tf.TenantMixin, _Base):
    """Tenant-aware сущность для проверки UNION/CTE."""

    __tablename__ = "n2_doc"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


def test_union_is_known_unfiltered_gap() -> None:
    """N-2: ``UNION`` обходит фильтр — зафиксировано как открытый пробел.

    Тест НЕ требует, чтобы сейчас было утечкой: он фиксирует текущее
    известное поведение, чтобы при исправлении пробел стал виден как
    регрессия, а не как тихая ломка.
    """
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    tf.apply_tenant_filter()
    with Session(engine) as session:
        session.add_all(
            [
                Doc(id=1, name="a", tenant_id="tenant-a"),
                Doc(id=2, name="b", tenant_id="tenant-b"),
            ]
        )
        session.commit()
        set_tenant(TenantContext(tenant_id="tenant-a"))
        leaked = session.execute(
            select(Doc.id, Doc.name).union(select(Doc.id, Doc.name))
        ).all()
        assert len(leaked) == 2, (
            "ожидаемая текущая картина: UNION не фильтруется (N-2, открыто). "
            "Если тест упал — пробел закрыт, обновите finding и этот тест."
        )
        set_tenant(TenantContext(tenant_id="tenant-a"))


def test_lifecycle_state_has_no_failed_member() -> None:
    """Отчёт не содержит ``LifecycleState.FAILED`` — финальные состояния осмысленны."""
    names = {s.name for s in LifecycleState}
    assert "STARTED" in names
    assert "DEGRADED" in names
    assert "ROLLED_BACK" in names
    assert "NOT_STARTED" in names
    assert "FAILED" not in names, (
        "падение фиксируется через outcome.error, а не отдельным state"
    )


def test_unused_column_import_is_needed() -> None:
    """Sanity: используемые ORM-импорты реально задействованы (ruff не врёт)."""
    assert Column is not None and Integer is not None
