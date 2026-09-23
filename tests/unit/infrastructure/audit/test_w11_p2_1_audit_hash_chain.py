"""Focused tests: W11 P2-1 — Audit log integrity hash chain (ADR-0340).

Validation:
1. Genesis entry (index 0) has prev_hash = 64 zeros.
2. Append creates entries with correct prev_hash linkage.
3. Canonical JSON serialization is deterministic (key order doesn't affect hash).
4. verify() detects tampering: payload change → hash mismatch.
5. verify() detects tampering: prev_hash change → chain break.
6. verify_with_gaps() detects missing entries (sequence gaps).
7. signed_checkpoint() returns head_hash + entry_count.
8. Restore scenario: ledger with gap → verify_with_gaps fails.

ADR-0340: audit log hash chain pattern.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.audit.hash_chain import (
    HashChainEntry,
    HashChainLedger,
    IntegrityStatus,
)

# ──────────────────── Append + basic invariants ────────────────────


class TestAppend:
    """Append создаёт корректные entries."""

    def test_genesis_entry_has_zero_prev_hash(self) -> None:
        ledger = HashChainLedger()
        e0 = ledger.append({"event": "login"})
        assert e0.index == 0
        assert e0.prev_hash == "0" * 64
        assert len(e0.current_hash) == 64  # SHA-256 hex digest

    def test_subsequent_entries_chain_via_prev_hash(self) -> None:
        ledger = HashChainLedger()
        e0 = ledger.append({"event": "a"})
        e1 = ledger.append({"event": "b"})
        e2 = ledger.append({"event": "c"})
        assert e1.prev_hash == e0.current_hash
        assert e2.prev_hash == e1.current_hash

    def test_indexes_are_contiguous(self) -> None:
        ledger = HashChainLedger()
        for i in range(5):
            entry = ledger.append({"i": i})
            assert entry.index == i

    def test_append_returns_immutable_entry(self) -> None:
        ledger = HashChainLedger()
        entry = ledger.append({"x": 1})
        with pytest.raises(Exception):  # FrozenInstanceError
            entry.payload = {"x": 2}  # type: ignore[misc]

    def test_custom_timestamp(self) -> None:
        ledger = HashChainLedger()
        entry = ledger.append({"x": 1}, timestamp=1234567890.0)
        assert entry.timestamp == 1234567890.0

    def test_custom_metadata(self) -> None:
        ledger = HashChainLedger()
        entry = ledger.append(
            {"event": "login"}, metadata={"operator_id": "alice"}
        )
        assert entry.metadata == {"operator_id": "alice"}


# ──────────────────── Canonical JSON ────────────────────


class TestCanonicalJson:
    """Canonical JSON serialization (key order не влияет на hash)."""

    def test_dict_key_order_doesnt_affect_hash(self) -> None:
        """Hash для {"a": 1, "b": 2} == Hash для {"b": 2, "a": 1}.

        Тот же timestamp нужен чтобы исключить его влияние.
        """
        ts = 1234567890.0
        ledger_a = HashChainLedger()
        ledger_b = HashChainLedger()
        e_a = ledger_a.append({"a": 1, "b": 2}, timestamp=ts)
        e_b = ledger_b.append({"b": 2, "a": 1}, timestamp=ts)
        assert e_a.current_hash == e_b.current_hash

    def test_nested_dict_key_order_doesnt_affect_hash(self) -> None:
        ts = 1234567890.0
        ledger_a = HashChainLedger()
        ledger_b = HashChainLedger()
        e_a = ledger_a.append({"user": {"id": 1, "name": "Alice"}}, timestamp=ts)
        e_b = ledger_b.append({"user": {"name": "Alice", "id": 1}}, timestamp=ts)
        assert e_a.current_hash == e_b.current_hash

    def test_unicode_payload_serialization(self) -> None:
        """Unicode payload сериализуется корректно."""
        ledger = HashChainLedger()
        entry = ledger.append({"name": "Алиса", "city": "Москва"})
        assert len(entry.current_hash) == 64

    def test_non_serializable_payload_raises(self) -> None:
        ledger = HashChainLedger()
        # set is not JSON-serializable.
        with pytest.raises(ValueError, match="JSON"):
            ledger.append({"tags": {1, 2, 3}})


# ──────────────────── Verify (basic) ────────────────────


class TestVerify:
    """verify() — проверка hash chain integrity."""

    def test_empty_ledger_is_valid(self) -> None:
        ledger = HashChainLedger()
        result = ledger.verify()
        assert result.is_valid is True
        assert result.status == IntegrityStatus.VALID
        assert result.entries_checked == 0

    def test_single_entry_valid(self) -> None:
        ledger = HashChainLedger()
        ledger.append({"x": 1})
        result = ledger.verify()
        assert result.is_valid is True
        assert result.entries_checked == 1

    def test_multiple_entries_valid(self) -> None:
        ledger = HashChainLedger()
        for i in range(10):
            ledger.append({"i": i})
        result = ledger.verify()
        assert result.is_valid is True
        assert result.entries_checked == 10

    def test_tampered_payload_detected(self) -> None:
        """Изменение payload → hash mismatch → tamper detected."""
        ledger = HashChainLedger()
        e0 = ledger.append({"event": "login", "user": "alice"})
        ledger.append({"event": "logout"})

        # Tamper: change payload (но сохраняем current_hash).
        # HashChainEntry frozen, so use _entries directly.
        ledger._entries[0] = HashChainEntry(
            index=e0.index,
            timestamp=e0.timestamp,
            payload={"event": "login", "user": "BOB"},  # changed
            prev_hash=e0.prev_hash,
            current_hash=e0.current_hash,  # но hash старый!
            metadata=e0.metadata,
        )

        result = ledger.verify()
        assert result.is_valid is False
        assert result.status == IntegrityStatus.TAMPERED
        assert result.first_tampered_index == 0

    def test_tampered_prev_hash_detected(self) -> None:
        """Изменение prev_hash → chain break."""
        ledger = HashChainLedger()
        ledger.append({"e": 1})
        e1 = ledger.append({"e": 2})
        ledger.append({"e": 3})

        # Tamper prev_hash второй записи (но оставляем current_hash).
        ledger._entries[1] = HashChainEntry(
            index=e1.index,
            timestamp=e1.timestamp,
            payload=e1.payload,
            prev_hash="0" * 64,  # invalid (должен быть хеш e0)
            current_hash=e1.current_hash,
            metadata=e1.metadata,
        )

        result = ledger.verify()
        assert result.is_valid is False
        assert result.status == IntegrityStatus.TAMPERED
        assert result.first_tampered_index == 1

    def test_tampered_timestamp_detected(self) -> None:
        """Изменение timestamp → hash mismatch."""
        ledger = HashChainLedger()
        e0 = ledger.append({"x": 1}, timestamp=1000.0)

        # Tamper timestamp.
        ledger._entries[0] = HashChainEntry(
            index=e0.index,
            timestamp=2000.0,  # changed
            payload=e0.payload,
            prev_hash=e0.prev_hash,
            current_hash=e0.current_hash,
            metadata=e0.metadata,
        )

        result = ledger.verify()
        assert result.is_valid is False
        assert result.status == IntegrityStatus.TAMPERED

    def test_invalid_genesis_detected(self) -> None:
        """Первая запись с не-genesis prev_hash → invalid."""
        ledger = HashChainLedger()
        e0 = ledger.append({"x": 1})

        # Set prev_hash to non-genesis (tamper genesis marker).
        ledger._entries[0] = HashChainEntry(
            index=e0.index,
            timestamp=e0.timestamp,
            payload=e0.payload,
            prev_hash="a" * 64,  # не genesis!
            current_hash=e0.current_hash,
            metadata=e0.metadata,
        )

        result = ledger.verify()
        assert result.is_valid is False
        assert result.status == IntegrityStatus.INVALID_GENESIS


# ──────────────────── Verify with gaps ────────────────────


class TestVerifyWithGaps:
    """verify_with_gaps() — detection of missing entries.

    Семантика:
    - ``verify()`` детектирует любую tamper (chain breakage).
    - ``verify_with_gaps()`` дополнительно: если chain не повреждён,
      но indexes non-contiguous → GAP_DETECTED.

    Realistic scenarios:
    - backup/restore с потерянным entry → chain breakage → TAMPERED.
    - Ручная реконструкция ledger с valid hashes но non-contiguous
      indexes → GAP_DETECTED (только через from_entries с валидным chain).
    """

    def test_contiguous_chain_is_valid(self) -> None:
        ledger = HashChainLedger()
        for i in range(5):
            ledger.append({"i": i})
        result = ledger.verify_with_gaps()
        assert result.is_valid is True

    def test_backup_restore_with_missing_entry_detected_as_tampered(self) -> None:
        """Realistic backup/restore scenario: missing entry breaks chain.

        Когда entry потерян при restore, prev_hash следующей записи
        указывает на хеш отсутствующей записи → chain breakage →
        TAMPERED (корректно: chain integrity нарушена).

        Это правильное поведение: backup/restore с потерей данных —
        это data integrity issue, который должен быть обнаружен.
        """
        source = HashChainLedger()
        for i in range(5):
            source.append({"i": i}, timestamp=1000.0 + i)

        # Restore: skip index 2, build new ledger.
        restored_entries = [e for e in source.get_entries() if e.index != 2]
        ledger = HashChainLedger.from_entries(restored_entries)

        result = ledger.verify_with_gaps()
        assert result.is_valid is False
        assert result.status == IntegrityStatus.TAMPERED
        assert result.first_tampered_index == 3  # first entry after gap

    def test_multiple_gaps_detected_as_tampered(self) -> None:
        """Multiple gaps в backup → TAMPERED at first missing prev_hash."""
        source = HashChainLedger()
        for i in range(6):
            source.append({"i": i}, timestamp=1000.0 + i)

        # Skip indexes 1 and 4.
        restored_entries = [
            e for e in source.get_entries() if e.index not in {1, 4}
        ]
        ledger = HashChainLedger.from_entries(restored_entries)

        result = ledger.verify_with_gaps()
        assert result.is_valid is False
        assert result.status == IntegrityStatus.TAMPERED

    def test_gap_detection_for_manual_reconstruction(self) -> None:
        """GAP_DETECTED для manually reconstructed ledger с valid hashes.

        Сценарий: ledger восстановлен с правильными хешами, но indexes
        пропущены (например, при ручной синхронизации из distributed replicas).

        Entry с index=2 отсутствует, но chain linkage остаётся valid:
        entry 3 ссылается на entry 1's hash, минуя index 2.
        """
        from src.backend.infrastructure.audit.hash_chain import (
            _GENESIS_HASH,
            _canonical_json,
            _compute_hash,
        )

        # Manually construct entries with non-contiguous indexes from scratch.
        ts0, ts1, ts3, ts4 = 1000.0, 2000.0, 4000.0, 5000.0
        e0 = HashChainEntry(
            index=0, timestamp=ts0, payload={"i": 0},
            prev_hash=_GENESIS_HASH,
            current_hash=_compute_hash(0, ts0, _canonical_json({"i": 0}), _GENESIS_HASH),
        )
        e1 = HashChainEntry(
            index=1, timestamp=ts1, payload={"i": 1},
            prev_hash=e0.current_hash,
            current_hash=_compute_hash(1, ts1, _canonical_json({"i": 1}), e0.current_hash),
        )
        # Skip index 2.
        e3 = HashChainEntry(
            index=3, timestamp=ts3, payload={"i": 3},
            prev_hash=e1.current_hash,  # link to e1 (skipping index 2)
            current_hash=_compute_hash(3, ts3, _canonical_json({"i": 3}), e1.current_hash),
        )
        e4 = HashChainEntry(
            index=4, timestamp=ts4, payload={"i": 4},
            prev_hash=e3.current_hash,
            current_hash=_compute_hash(4, ts4, _canonical_json({"i": 4}), e3.current_hash),
        )

        ledger = HashChainLedger.from_entries([e0, e1, e3, e4])
        result = ledger.verify_with_gaps()

        assert result.is_valid is False
        assert result.status == IntegrityStatus.GAP_DETECTED
        assert result.first_gap_at == 2

    def test_restore_scenario_with_verified_gaps(self) -> None:
        """Realistic restore scenario: chain break → TAMPERED.

        Per v4 evidence-first protocol, тест документирует realistic behavior:
        backup/restore с missing entry → TAMPERED, не GAP_DETECTED.
        """
        source = HashChainLedger()
        for i in range(5):
            source.append({"event": f"event-{i}"}, timestamp=1000.0 + i)

        # Restore: copy entries (skipping index 2), preserve original indexes.
        restored_entries = [e for e in source.get_entries() if e.index != 2]
        restored = HashChainLedger.from_entries(restored_entries)

        result = restored.verify_with_gaps()
        assert result.is_valid is False
        # Realistic: missing entry breaks chain → TAMPERED.
        assert result.status == IntegrityStatus.TAMPERED


# ──────────────────── Read-only access ────────────────────


class TestReadOnlyAccess:
    """Read-only access к entries (для export/audit log review)."""

    def test_len(self) -> None:
        ledger = HashChainLedger()
        assert len(ledger) == 0
        ledger.append({"x": 1})
        assert len(ledger) == 1

    def test_getitem(self) -> None:
        ledger = HashChainLedger()
        e0 = ledger.append({"x": 1})
        assert ledger[0] is e0

    def test_iter(self) -> None:
        ledger = HashChainLedger()
        for i in range(3):
            ledger.append({"i": i})
        indexes = [e.index for e in ledger]
        assert indexes == [0, 1, 2]

    def test_get_entries_returns_copy(self) -> None:
        ledger = HashChainLedger()
        ledger.append({"x": 1})
        entries = ledger.get_entries()
        entries.clear()  # modifying returned list shouldn't affect ledger
        assert len(ledger) == 1


# ──────────────────── Signed checkpoint ────────────────────


class TestSignedCheckpoint:
    """Checkpoint snapshot для external signing (placeholder)."""

    def test_empty_ledger_checkpoint(self) -> None:
        ledger = HashChainLedger()
        checkpoint = ledger.signed_checkpoint()
        assert checkpoint["head_hash"] == "0" * 64
        assert checkpoint["entry_count"] == 0
        assert "timestamp" in checkpoint

    def test_non_empty_ledger_checkpoint(self) -> None:
        ledger = HashChainLedger()
        ledger.append({"e": 1})
        ledger.append({"e": 2})
        checkpoint = ledger.signed_checkpoint()
        assert checkpoint["head_hash"] == ledger[-1].current_hash
        assert checkpoint["entry_count"] == 2


# ──────────────────── End-to-end scenarios ────────────────────


class TestEndToEndScenarios:
    """Realistic scenarios из strategic analysis 2026-09-22."""

    def test_plugin_install_audit_chain(self) -> None:
        """Plugin install → audit chain (per strategic analysis)."""
        ledger = HashChainLedger()
        ledger.append(
            {"action": "plugin_install", "plugin": "core_entities", "version": "1.0.0"},
            metadata={"operator_id": "admin", "source": "admin_panel"},
        )
        ledger.append(
            {"action": "plugin_enable", "plugin": "core_entities"},
            metadata={"operator_id": "admin"},
        )

        result = ledger.verify_with_gaps()
        assert result.is_valid is True

    def test_route_change_audit_chain(self) -> None:
        """Route change → audit chain (per strategic analysis)."""
        ledger = HashChainLedger()
        ledger.append(
            {"action": "route_create", "route_id": "orders.sync"},
            metadata={"operator_id": "alice"},
        )
        ledger.append(
            {"action": "route_deploy", "route_id": "orders.sync"},
            metadata={"operator_id": "alice", "deployment_id": "dep-123"},
        )

        result = ledger.verify_with_gaps()
        assert result.is_valid is True

    def test_dlq_replay_audit_chain(self) -> None:
        """DLQ replay (W11 P1-2 integration) → audit chain."""
        ledger = HashChainLedger()
        # Correlate with W11 P1-2 ReplayAuditEntry.
        ledger.append(
            {
                "action": "dlq_replay",
                "replay_id": "r-123",
                "original_event_id": "evt-456",
                "operator_id": "alice",
                "reason": "ops-incident-42",
            },
        )
        result = ledger.verify_with_gaps()
        assert result.is_valid is True

    def test_secret_rotation_audit_chain(self) -> None:
        """Secret rotation → audit chain."""
        ledger = HashChainLedger()
        ledger.append(
            {
                "action": "secret_rotation",
                "secret_name": "JWT_SIGNING_KEY",
                "overlap_period_s": 3600,
            },
            metadata={"operator_id": "security_team"},
        )
        ledger.append(
            {"action": "secret_rotation_complete", "secret_name": "JWT_SIGNING_KEY"},
            metadata={"operator_id": "security_team"},
        )

        result = ledger.verify_with_gaps()
        assert result.is_valid is True


# ──────────────────── Performance / scale ────────────────────


class TestPerformance:
    """Sanity check: verify() работает на 1000+ entries."""

    def test_1000_entries_verify(self) -> None:
        ledger = HashChainLedger()
        for i in range(1000):
            ledger.append({"i": i, "event": f"event-{i}"})
        result = ledger.verify_with_gaps()
        assert result.is_valid is True
        assert result.entries_checked == 1000
