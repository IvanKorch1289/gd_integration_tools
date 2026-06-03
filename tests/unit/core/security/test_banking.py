"""Tests for banking security module."""

from __future__ import annotations

from datetime import datetime, timezone

from src.backend.core.security.banking import (
    AntiFraudEngine,
    AntiFraudRule,
    DummyCryptoProvider,
    SignedTransaction,
    SoftwareHsmBackend,
    TxSigner,
)


class TestDummyCryptoProvider:
    def test_sign_verify_roundtrip(self) -> None:
        cp = DummyCryptoProvider(b"secret")
        data = b"payload"
        sig = cp.sign(data, "key-1")
        assert cp.verify(data, sig, "key-1") is True

    def test_verify_fails_on_bad_sig(self) -> None:
        cp = DummyCryptoProvider(b"secret")
        assert cp.verify(b"a", b"bad", "key") is False

    def test_hash(self) -> None:
        cp = DummyCryptoProvider()
        h1 = cp.hash(b"a")
        h2 = cp.hash(b"a")
        assert h1 == h2
        assert len(h1) == 32

    def test_default_secret_random(self) -> None:
        cp1 = DummyCryptoProvider()
        cp2 = DummyCryptoProvider()
        assert cp1.sign(b"x", "k") != cp2.sign(b"x", "k")


class TestSoftwareHsmBackend:
    def test_load_key_returns_key_id(self) -> None:
        cp = DummyCryptoProvider(b"s")
        hsm = SoftwareHsmBackend(cp)
        assert hsm.load_key("k1") == "k1"

    def test_sign_with_hsm_delegates(self) -> None:
        cp = DummyCryptoProvider(b"s")
        hsm = SoftwareHsmBackend(cp)
        data = b"d"
        sig = hsm.sign_with_hsm(data, "k1")
        assert cp.verify(data, sig, "k1") is True


class TestTxSigner:
    def test_sign_produces_signed_transaction(self) -> None:
        cp = DummyCryptoProvider(b"s")
        signer = TxSigner(cp)
        tx = signer.sign(b"payload", "key-1")
        assert isinstance(tx, SignedTransaction)
        assert tx.payload == b"payload"
        assert tx.key_id == "key-1"
        assert tx.algorithm == "GOST-R-34.10-2012"
        assert isinstance(tx.signed_at, datetime)

    def test_verify_true(self) -> None:
        cp = DummyCryptoProvider(b"s")
        signer = TxSigner(cp)
        tx = signer.sign(b"p", "k")
        assert signer.verify(tx) is True

    def test_verify_false(self) -> None:
        cp = DummyCryptoProvider(b"s")
        signer = TxSigner(cp)
        tx = signer.sign(b"p", "k")
        bad_tx = SignedTransaction(
            payload=b"x",
            signature=tx.signature,
            key_id="k",
            signed_at=datetime.now(timezone.utc),
        )
        assert signer.verify(bad_tx) is False


class TestAntiFraudEngine:
    def test_no_rules_empty(self) -> None:
        engine = AntiFraudEngine()
        assert engine.evaluate({"amount": 100}) == []

    def test_rule_triggers(self) -> None:
        rule = AntiFraudRule(
            name="high_amount", predicate=lambda tx: tx["amount"] > 500
        )
        engine = AntiFraudEngine([rule])
        triggered = engine.evaluate({"amount": 600})
        assert len(triggered) == 1
        assert triggered[0].name == "high_amount"

    def test_rule_skipped_on_exception(self) -> None:
        rule = AntiFraudRule(
            name="broken", predicate=lambda _tx: (_tx["missing"])
        )
        engine = AntiFraudEngine([rule])
        assert engine.evaluate({"amount": 100}) == []

    def test_is_blocked(self) -> None:
        block_rule = AntiFraudRule(
            name="block_big", predicate=lambda tx: tx["amount"] > 1000, severity="block"
        )
        warn_rule = AntiFraudRule(
            name="warn_mid", predicate=lambda tx: tx["amount"] > 500, severity="warn"
        )
        engine = AntiFraudEngine([warn_rule, block_rule])
        assert engine.is_blocked({"amount": 600}) is False
        assert engine.is_blocked({"amount": 1200}) is True

    def test_register_adds_rule(self) -> None:
        engine = AntiFraudEngine()
        engine.register(AntiFraudRule(name="r1", predicate=lambda _x: True))
        assert len(engine._rules) == 1
