"""Immutable append-only audit log с HMAC-chain (IL-SEC2).

Каждое событие содержит:

    * ``prev_hash`` — HMAC-SHA256 предыдущего события (или "0"*64 для первого);
    * ``event_hash`` — HMAC-SHA256(canonical_json(this_event) || prev_hash).

Цепочка связывает события: если злоумышленник удалит или отредактирует
любое событие, ``verify()`` обнаружит разрыв цепи — HMAC не сойдётся.

**Почему Postgres, а не Redis stream?**

* Redis stream — mutable (XDEL / XTRIM / FLUSHDB доступны).
* Postgres table с HMAC-chain — durable, replicable, exportable (для
  соответствия SOC 2 Type II CC7.2 и внешних аудитов).
* Backup-ы можно подписывать отдельно (WAL + pg_basebackup).

**Политика целостности (tamper detection):**

* на запись — lock-free (INSERT + последний seq читается без FOR UPDATE,
  так как seq monotonic через BIGSERIAL), но для корректной цепочки
  используется advisory lock на таблицу во время append;
* на верификацию — sequential walk от seq=1 до последнего.

HMAC-секрет хранится в ``settings.secure.audit_secret_key`` (env
``AUDIT_SECRET_KEY``). При отсутствии — fallback на ``settings.secure.secret_key``
с warning в лог.

Пример использования::

    store = ImmutableAuditStore(session_factory=db.get_session)
    await store.append(
        actor="user_42",
        action="orders.delete",
        resource="order:1337",
        outcome="success",
        tenant_id="acme",
        metadata={"reason": "customer request"},
    )

    # Периодически (cron / startup / admin endpoint):
    result = await store.verify()
    if not result.valid:
        alert(f"audit log tampered at seq={result.first_broken_seq}")
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from src.backend.utilities.codecs.json import canonical_json_bytes, dumps_str

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


__all__ = ("ImmutableAuditStore", "VerifyResult", "AuditIntegrityError")


logger = logging.getLogger("observability.immutable_audit")

_TABLE = "audit_log_immutable"
_GENESIS_HASH = "0" * 64  # prev_hash для первого события цепи
_ADVISORY_LOCK_KEY = 0x61756469745F6C6F67  # int64 от b"audit_log" (хэш-подобный)


class AuditIntegrityError(RuntimeError):
    """Нарушение целостности цепи audit log."""


@dataclass(slots=True, frozen=True)
class VerifyResult:
    """Результат проверки цепочки audit log."""

    valid: bool
    total_checked: int
    first_broken_seq: int | None
    details: str


class ImmutableAuditStore:
    """Append-only HMAC-chained audit log поверх Postgres.

    Параметры:
        session_factory: async-callable → ``AsyncSession`` (контекст-менеджер
            или async generator). Обычно ``db.get_session`` проекта.
        secret_key: HMAC-ключ (bytes/str). Если None — читается из
            ``AUDIT_SECRET_KEY``, затем из ``settings.secure.secret_key``.
        table_name: имя таблицы (default ``audit_log_immutable``).
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        secret_key: bytes | str | None = None,
        table_name: str = _TABLE,
    ) -> None:
        self._session_factory = session_factory
        self._table = table_name
        self._secret = self._resolve_secret(secret_key)

    # ------------------------------------------------------------------ utils

    @staticmethod
    def _resolve_secret(explicit: bytes | str | None) -> bytes:
        if explicit is not None:
            return explicit.encode("utf-8") if isinstance(explicit, str) else explicit
        env_key = os.getenv("AUDIT_SECRET_KEY")
        if env_key:
            return env_key.encode("utf-8")
        # Fallback на глобальный secret_key; это не идеально (shared blast
        # radius), но лучше чем hardcoded default.
        try:
            from src.backend.core.config.settings import settings  # local import

            fallback = getattr(settings.secure, "secret_key", None)
            if fallback:
                logger.warning(
                    "AUDIT_SECRET_KEY не задан — использую secure.secret_key "
                    "как fallback. Рекомендуется выделить отдельный ключ."
                )
                return (
                    fallback.encode("utf-8") if isinstance(fallback, str) else fallback
                )
        except Exception as exc:  # noqa: BLE001 — settings might be unavailable
            logger.error("Не удалось прочитать fallback secret_key: %s", exc)
        logger.error(
            "AUDIT_SECRET_KEY отсутствует — использую пустой ключ "
            "(integrity guarantees ослаблены!)"
        )
        return b""

    @staticmethod
    def _canonical_json(event: dict[str, Any]) -> bytes:
        """Детерминированный JSON для HMAC.

        Делегирует в общий ``canonical_json_bytes`` (codecs.json) — единая
        формула канонизации для HMAC-chain / doc_id / dedup-key. На stdlib
        json для byte-стабильности с ранее записанными в БД хешами.
        """
        return canonical_json_bytes(event)

    def _hmac(self, payload: bytes, prev_hash: str) -> str:
        h = hmac.new(self._secret, digestmod=hashlib.sha256)
        h.update(payload)
        h.update(b"|")
        h.update(prev_hash.encode("ascii"))
        return h.hexdigest()

    # ---------------------------------------------------------------- session

    def _acquire_session(self) -> Any:
        """Возвращает либо async context manager, либо async generator-обёртку.

        Поддерживает оба варианта session_factory, использующихся в проекте:
        ``async with factory() as session:`` и ``async for session in factory():``.
        """
        return self._session_factory()

    # ----------------------------------------------------------------- append

    async def append(
        self,
        *,
        actor: str,
        action: str,
        resource: str | None = None,
        outcome: str,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
        correlation_id: str | None = None,
    ) -> str:
        """Добавляет событие, возвращает его ``event_hash`` (hex).

        Алгоритм:
            1. Берём advisory lock на уровне БД (предотвращает race с другим
               writer-ом в пределах кластера Postgres).
            2. Читаем последний ``event_hash`` (или GENESIS).
            3. Строим canonical JSON + считаем HMAC.
            4. INSERT-им запись.
            5. Отпускаем lock (автоматически на commit/rollback).

        :returns: hex-строка ``event_hash`` — клиент может сохранить для
            последующего ad-hoc verify.
        """
        from sqlalchemy import text  # local import, чтобы модуль был ленивым

        occurred_at = datetime.now(timezone.utc)
        event_dict = {
            "actor": actor,
            "action": action,
            "resource": resource,
            "outcome": outcome,
            "metadata": metadata or {},
            "tenant_id": tenant_id,
            "correlation_id": correlation_id,
            # occurred_at в canonical-форме, чтобы HMAC не зависел от
            # форматирования БД.
            "occurred_at": occurred_at.isoformat(),
        }
        payload = self._canonical_json(event_dict)

        async with self._session_scope() as session:
            # pg_advisory_xact_lock — отпускается на commit/rollback.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_LOCK_KEY}
            )
            prev_row = (
                await session.execute(
                    text(
                        f"SELECT event_hash FROM {self._table} "  # noqa: S608  # self._table — ctor-parameter, не user input
                        f"ORDER BY seq DESC LIMIT 1"
                    )
                )
            ).first()
            prev_hash = prev_row[0] if prev_row else _GENESIS_HASH
            event_hash = self._hmac(payload, prev_hash)

            await session.execute(
                text(
                    f"INSERT INTO {self._table} "  # noqa: S608  # self._table — ctor-parameter, не user input
                    f"(actor, action, resource, outcome, metadata, "
                    f" tenant_id, correlation_id, prev_hash, event_hash, "
                    f" occurred_at) "
                    f"VALUES (:actor, :action, :resource, :outcome, "
                    f" CAST(:metadata AS JSONB), :tenant_id, "
                    f" :correlation_id, :prev_hash, :event_hash, "
                    f" :occurred_at)"
                ),
                {
                    "actor": actor,
                    "action": action,
                    "resource": resource,
                    "outcome": outcome,
                    "metadata": dumps_str(metadata or {}),
                    "tenant_id": tenant_id,
                    "correlation_id": correlation_id,
                    "prev_hash": prev_hash,
                    "event_hash": event_hash,
                    "occurred_at": occurred_at,
                },
            )
            await session.commit()

        return event_hash

    # ----------------------------------------------------------------- verify

    async def verify(
        self, from_seq: int = 0, to_seq: int | None = None
    ) -> VerifyResult:
        """Проверяет HMAC-цепочку от ``from_seq`` до ``to_seq`` (включительно).

        Если ``to_seq is None`` — до последнего события.

        :returns: ``VerifyResult(valid, total_checked, first_broken_seq, details)``.
            При `valid=False` ``first_broken_seq`` содержит seq первой
            скомпрометированной записи.
        """
        from sqlalchemy import text

        sql = (
            f"SELECT seq, actor, action, resource, outcome, metadata, "  # noqa: S608  # self._table — ctor-parameter, не user input
            f" tenant_id, correlation_id, prev_hash, event_hash, occurred_at "
            f"FROM {self._table} "
            f"WHERE seq >= :from_seq "
            + ("AND seq <= :to_seq " if to_seq is not None else "")
            + "ORDER BY seq ASC"
        )
        params: dict[str, Any] = {"from_seq": from_seq}
        if to_seq is not None:
            params["to_seq"] = to_seq

        async with self._session_scope() as session:
            rows = (await session.execute(text(sql), params)).all()

        if not rows:
            return VerifyResult(
                valid=True,
                total_checked=0,
                first_broken_seq=None,
                details="audit log пуст в указанном диапазоне",
            )

        # Для первого события в диапазоне prev_hash должен совпадать с
        # event_hash предыдущего seq (или GENESIS, если это seq=1).
        first = rows[0]
        if int(first[0]) > 1:
            async with self._session_scope() as session:
                anchor_row = (
                    await session.execute(
                        text(f"SELECT event_hash FROM {self._table} WHERE seq = :s"),  # noqa: S608  # self._table — ctor-parameter, не user input
                        {"s": int(first[0]) - 1},
                    )
                ).first()
            expected_anchor = anchor_row[0] if anchor_row else _GENESIS_HASH
        else:
            expected_anchor = _GENESIS_HASH

        running_prev = expected_anchor
        checked = 0
        for row in rows:
            (
                seq,
                actor,
                action,
                resource,
                outcome,
                metadata,
                tenant_id,
                correlation_id,
                prev_hash,
                event_hash,
                occurred_at,
            ) = row
            # Проверка 1: prev_hash в записи совпадает с ожидаемым якорем.
            if prev_hash != running_prev:
                return VerifyResult(
                    valid=False,
                    total_checked=checked,
                    first_broken_seq=int(seq),
                    details=(
                        f"seq={seq}: prev_hash mismatch "
                        f"(expected {running_prev[:12]}…, got {prev_hash[:12]}…)"
                    ),
                )
            # Проверка 2: HMAC payload-а совпадает с сохранённым event_hash.
            event_dict = {
                "actor": actor,
                "action": action,
                "resource": resource,
                "outcome": outcome,
                "metadata": metadata if metadata is not None else {},
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "occurred_at": (
                    occurred_at.isoformat()
                    if hasattr(occurred_at, "isoformat")
                    else str(occurred_at)
                ),
            }
            expected_hash = self._hmac(self._canonical_json(event_dict), prev_hash)
            if expected_hash != event_hash:
                return VerifyResult(
                    valid=False,
                    total_checked=checked,
                    first_broken_seq=int(seq),
                    details=(
                        f"seq={seq}: event_hash mismatch — запись "
                        f"отредактирована или HMAC-ключ сменён"
                    ),
                )
            running_prev = event_hash
            checked += 1

        return VerifyResult(
            valid=True,
            total_checked=checked,
            first_broken_seq=None,
            details=f"цепочка валидна ({checked} событий)",
        )

    # ------------------------------------------------------------- internals

    def _session_scope(self):
        """Возвращает async-context-manager поверх session_factory.

        session_factory в проекте может быть:
            * async generator (``async def get_session(): yield session``)
            * async context manager (``async with factory() as s: ...``)

        Мы оборачиваем оба варианта в единый интерфейс.
        """
        factory_result = self._session_factory()
        return _SessionScope(factory_result)


class _SessionScope:
    """Унифицированный async-context-manager поверх generator/CM."""

    def __init__(self, factory_result: Any) -> None:
        self._src = factory_result
        self._gen: Any = None

    async def __aenter__(self) -> "AsyncSession":
        # Вариант 1: async context manager.
        if hasattr(self._src, "__aenter__"):
            self._gen = self._src
            return await self._src.__aenter__()
        # Вариант 2: async generator.
        if hasattr(self._src, "__anext__"):
            self._gen = self._src
            return await self._src.__anext__()
        # Вариант 3: awaitable, отдающий session напрямую.
        if hasattr(self._src, "__await__"):
            session = await self._src
            self._gen = None
            return session
        raise TypeError(
            f"session_factory вернул объект неподдерживаемого типа: "
            f"{type(self._src).__name__}"
        )

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._gen is None:
            return
        if hasattr(self._gen, "__aexit__"):
            await self._gen.__aexit__(exc_type, exc, tb)
            return
        if hasattr(self._gen, "aclose"):
            try:
                await self._gen.aclose()
            except StopAsyncIteration:
                pass
