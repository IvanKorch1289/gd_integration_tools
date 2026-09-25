"""Audit log integrity — hash chain ledger (W11 P2-1, ADR-0340).

Стратегический анализ 2026-09-22 (timestamp 1790089356160) выявил gap:

> «Обычный audit log может быть изменён вместе с основной БД. Для
> критических действий нужны:
>   - Hash chaining.
>   - External immutable sink.
>   - Sequence-gap detection.
>   - Signed checkpoints.
>   - Separation of duties.
>   - Retention lock.
>   - Проверка восстановления цепочки после backup/restore.
> …
> Это особенно важно для plugin installation, route changes,
> impersonation, secret rotation, feature flags и DLQ replay.»

Этот модуль реализует **hash chain ledger** — append-only структуру с
криптографической цепочкой. Каждая запись содержит SHA-256 хеш предыдущей
записи, что делает невозможным изменение одной записи без разрушения
chain (любая tamper попытка видна на verify).

Design:
- **Append-only**: entries никогда не модифицируются после добавления.
- **Hash chain**: entry N's hash = SHA256(index | timestamp | payload | prev_hash).
- **Canonical JSON**: payload сериализуется через ``json.dumps(sort_keys=True,
  separators=(",", ":"))`` для детерминизма (порядок ключей не влияет на hash).
- **Sequence integrity**: ``verify_with_gaps()`` обнаруживает missing entries
  (если indexes не contiguous).
- **Restore support**: ``verify_with_gaps()`` полезен после backup/restore
  для проверки, что ни одна запись не потерялась.

Использование::

    ledger = HashChainLedger()

    # Append entries.
    e0 = ledger.append({"event": "login", "user": "alice"})
    e1 = ledger.append({"event": "create_order", "order_id": "123"})
    e2 = ledger.append({"event": "logout", "user": "alice"})

    # Verify chain.
    result = ledger.verify()
    assert result.is_valid

    # Detect tampering.
    ledger._entries[1].payload = '{"event": "create_order", "order_id": "999"}'  # tamper
    result = ledger.verify()
    assert not result.is_valid
    assert result.first_tampered_index == 1

    # Gap detection.
    ledger2 = HashChainLedger()
    ledger2.append({...})  # index 0
    ledger2.append({...})  # index 1
    # remove index 1 (simulate lost entry)
    del ledger2._entries[1]
    result = ledger2.verify_with_gaps()
    assert not result.is_valid
    assert result.gap_detected

ADR-0340: audit log hash chain pattern.

Не покрыто в этом модуле (out of scope):
- External immutable sink (W11 P2-1 backlog: Kafka append-only topic).
- Signed checkpoints (placeholder hook в ``signed_checkpoint()``).
- Separation of duties (governance layer).
- Retention lock (DB-level; см. ``infrastructure/audit/migrations/``).

Integration: ``src/backend/services/audit/workflow_audit_sink.py`` может
использовать ``HashChainLedger`` для добавления integrity layer поверх
ClickHouse storage. Production deployment: каждая критическая операция
(``plugin install``, ``route change``, ``impersonation``, ``secret rotation``,
``feature flag toggle``, ``DLQ replay`` per W11 P1-2) должна писать в
hash chain ledger.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = (
    "ChainVerificationResult",
    "HashChainEntry",
    "HashChainLedger",
    "IntegrityStatus",
)


# Genesis hash (для первой записи в цепочке).
_GENESIS_HASH = "0" * 64


# ──────────────────── HashChainEntry ────────────────────


@dataclass(frozen=True, slots=True)
class HashChainEntry:
    """Одна запись в hash chain ledger.

    Attributes:
        index: Sequence number (0-based, contiguous). Обнаружение gaps.
        timestamp: Unix timestamp (float, seconds).
        payload: Оригинальный payload (dict → JSON перед хешированием).
        prev_hash: SHA-256 hex digest предыдущей записи (или genesis).
        current_hash: SHA-256 hex digest этой записи.
        metadata: Произвольные пары ключ-значение (operator_id, source, etc.).
            НЕ включаются в хеш (для гибкости; включаются при необходимости).

    Invariants:
        - После создания entry immutable (frozen=True).
        - current_hash = SHA256(index | timestamp | canonical_json(payload) | prev_hash).
    """

    index: int
    timestamp: float
    payload: Any
    prev_hash: str
    current_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ──────────────────── Verification result ────────────────────


class IntegrityStatus(StrEnum):
    """Статус integrity check для ledger."""

    VALID = "valid"
    """Все entries корректны, нет tamper или gaps."""

    TAMPERED = "tampered"
    """Hash mismatch обнаружен в одной или нескольких entries."""

    GAP_DETECTED = "gap_detected"
    """Sequence gap (missing indexes между entries)."""

    INVALID_GENESIS = "invalid_genesis"
    """Первая запись имеет prev_hash != GENESIS_HASH."""


@dataclass(frozen=True, slots=True)
class ChainVerificationResult:
    """Результат verify() или verify_with_gaps().

    Attributes:
        status: IntegrityStatus.
        is_valid: True если status == VALID.
        entries_checked: Сколько entries проверено.
        first_tampered_index: Index первой tamper'нутой записи (если есть).
        first_gap_at: Index где обнаружен gap (е.g., expected_index).
        total_gaps: Сколько gaps обнаружено.
    """

    status: IntegrityStatus
    is_valid: bool
    entries_checked: int
    first_tampered_index: int | None = None
    first_gap_at: int | None = None
    total_gaps: int = 0


# ──────────────────── HashChainLedger ────────────────────


class HashChainLedger:
    """Append-only ledger с cryptographic hash chain.

    Используется для audit log integrity — каждая запись криптографически
    связана с предыдущей через SHA-256. Любая модификация записи
    (даже одной) делает невалидной всю последующую цепочку.

    Thread-safety: не thread-safe (single-writer assumption). Для
    multi-writer — wrap в asyncio.Lock или external coordination.
    """

    def __init__(self) -> None:
        self._entries: list[HashChainEntry] = []

    # ─────────── Append ───────────

    def append(
        self,
        payload: Any,
        *,
        metadata: Mapping[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> HashChainEntry:
        """Добавляет новую запись в chain.

        Args:
            payload: Данные для записи (dict, list, str, любой JSON-сериализуемый).
            metadata: Опциональные метаданные (operator_id, source, etc.).
            timestamp: Опц. timestamp (default: time.time()).

        Returns:
            Созданная запись (frozen, immutable).

        Raises:
            ValueError: Если payload не сериализуется в JSON.
        """
        index = len(self._entries)
        prev_hash = self._entries[-1].current_hash if self._entries else _GENESIS_HASH
        ts = timestamp if timestamp is not None else time.time()
        canonical = _canonical_json(payload)
        current_hash = _compute_hash(index, ts, canonical, prev_hash)

        entry = HashChainEntry(
            index=index,
            timestamp=ts,
            payload=payload,
            prev_hash=prev_hash,
            current_hash=current_hash,
            metadata=dict(metadata or {}),
        )
        self._entries.append(entry)
        return entry

    @classmethod
    def from_entries(cls, entries: list[HashChainEntry]) -> "HashChainLedger":
        """Создаёт ledger из existing entries (для restore scenario).

        Сохраняет original indexes (включая gaps, если entries были потеряны
        при backup/restore). Позволяет ``verify_with_gaps()`` детектировать
        потерю entries через missing indexes.

        Args:
            entries: Список HashChainEntry для восстановления.

        Returns:
            Новый ledger с указанными entries (deep-copied list).

        Note:
            Не валидирует chain integrity — вызывающий должен вызвать
            ``verify()`` или ``verify_with_gaps()`` после restore.
        """
        ledger = cls()
        # Deep-copy entries list (HashChainEntry frozen, list contents immutable).
        ledger._entries = list(entries)
        return ledger

    # ─────────── Verification ───────────

    def verify(self) -> ChainVerificationResult:
        """Проверяет hash chain: каждый entry's current_hash корректен.

        Returns:
            ChainVerificationResult с is_valid=True если chain невредим.
        """
        if not self._entries:
            return ChainVerificationResult(
                status=IntegrityStatus.VALID, is_valid=True, entries_checked=0
            )

        # Genesis check.
        if self._entries[0].prev_hash != _GENESIS_HASH:
            return ChainVerificationResult(
                status=IntegrityStatus.INVALID_GENESIS,
                is_valid=False,
                entries_checked=1,
                first_tampered_index=0,
            )

        prev_hash = _GENESIS_HASH
        for entry in self._entries:
            # Verify prev_hash linkage.
            if entry.prev_hash != prev_hash:
                return ChainVerificationResult(
                    status=IntegrityStatus.TAMPERED,
                    is_valid=False,
                    entries_checked=entry.index + 1,
                    first_tampered_index=entry.index,
                )
            # Verify current_hash.
            canonical = _canonical_json(entry.payload)
            expected = _compute_hash(
                entry.index, entry.timestamp, canonical, entry.prev_hash
            )
            if entry.current_hash != expected:
                return ChainVerificationResult(
                    status=IntegrityStatus.TAMPERED,
                    is_valid=False,
                    entries_checked=entry.index + 1,
                    first_tampered_index=entry.index,
                )
            prev_hash = entry.current_hash

        return ChainVerificationResult(
            status=IntegrityStatus.VALID,
            is_valid=True,
            entries_checked=len(self._entries),
        )

    def verify_with_gaps(self) -> ChainVerificationResult:
        """verify() + detection of missing entries (sequence gaps).

        Use case: после backup/restore проверить, что ни одна запись
        не была потеряна. Если indexes не contiguous (e.g., 0, 1, 3, 4
        — отсутствует index 2), это GAP.

        Returns:
            ChainVerificationResult с is_valid=False если gaps или tamper.
        """
        # Сначала обычный verify.
        basic = self.verify()
        if not basic.is_valid:
            return basic

        # Проверяем contiguous indexes.
        expected_index = 0
        for entry in self._entries:
            if entry.index != expected_index:
                return ChainVerificationResult(
                    status=IntegrityStatus.GAP_DETECTED,
                    is_valid=False,
                    entries_checked=expected_index,
                    first_gap_at=expected_index,
                    total_gaps=self._count_gaps(),
                )
            expected_index += 1

        return basic  # valid, no gaps

    def _count_gaps(self) -> int:
        """Считает сколько indexes пропущено."""
        if not self._entries:
            return 0
        expected = list(range(self._entries[-1].index + 1))
        actual = {e.index for e in self._entries}
        return len([i for i in expected if i not in actual])

    # ─────────── Read-only access ───────────

    def __len__(self) -> int:
        return len(self._entries)

    def __getitem__(self, index: int) -> HashChainEntry:
        return self._entries[index]

    def __iter__(self):
        return iter(self._entries)

    def get_entries(self) -> list[HashChainEntry]:
        """Возвращает shallow copy entries (read-only convention)."""
        return list(self._entries)

    # ─────────── Checkpoints (placeholder for signed) ───────────

    def signed_checkpoint(self) -> dict[str, Any]:
        """Создаёт checkpoint snapshot для external signing.

        Placeholder: в production checkpoint подписывается external KMS
        (Vault Transit, AWS KMS) и публикуется в immutable sink
        (Kafka append-only topic, S3 Object Lock).

        Returns:
            Dict с current_head_hash, entry_count, timestamp.
        """
        return {
            "head_hash": self._entries[-1].current_hash
            if self._entries
            else _GENESIS_HASH,
            "entry_count": len(self._entries),
            "timestamp": time.time(),
        }


# ──────────────────── Internal helpers ────────────────────


def _canonical_json(payload: Any) -> str:
    """Canonical JSON serialization для детерминизма hash'а.

    Args:
        payload: Любой JSON-сериализуемый объект.

    Returns:
        Compact JSON: sorted_keys, separators=(",", ":").

    Raises:
        ValueError: Если payload не сериализуется в JSON.
    """
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Payload не сериализуется в JSON: {exc}. "
            f"Используйте dict/list/str/int/float/bool/None."
        ) from exc


def _compute_hash(
    index: int, timestamp: float, canonical_payload: str, prev_hash: str
) -> str:
    """SHA-256 hash от canonical representation.

    Args:
        index: Sequence number.
        timestamp: Unix timestamp.
        canonical_payload: Canonical JSON string.
        prev_hash: SHA-256 hex digest предыдущей записи.

    Returns:
        64-char hex digest.
    """
    h = hashlib.sha256()
    h.update(f"{index}|{timestamp}|{canonical_payload}|{prev_hash}".encode("utf-8"))
    return h.hexdigest()
