# ruff: noqa: S101
"""Тесты CapabilityGate + check_capabilities_subset (ADR-044)."""

from __future__ import annotations

from typing import Any

import pytest

from src.core.security.capabilities import (
    CapabilityDef,
    CapabilityDeniedError,
    CapabilityGate,
    CapabilityRef,
    CapabilitySupersetError,
    CapabilityVocabulary,
    ExactAliasMatcher,
    GlobScopeMatcher,
    build_default_vocabulary,
    check_capabilities_subset,
)

# ── CapabilityGate ────────────────────────────────────────────────────


class TestCapabilityGate:
    def test_check_granted(self) -> None:
        gate = CapabilityGate()
        gate.declare("p1", [CapabilityRef(name="db.read", scope="credit_db")])
        gate.check("p1", "db.read", "credit_db")  # no raise

    def test_check_denied_no_declaration(self) -> None:
        gate = CapabilityGate()
        with pytest.raises(CapabilityDeniedError) as exc:
            gate.check("p1", "db.read", "credit_db")
        assert exc.value.declared_scope is None

    def test_check_denied_scope_mismatch(self) -> None:
        gate = CapabilityGate()
        gate.declare("p1", [CapabilityRef(name="db.read", scope="credit_db")])
        with pytest.raises(CapabilityDeniedError) as exc:
            gate.check("p1", "db.read", "audit_db")
        assert exc.value.declared_scope == "credit_db"
        assert exc.value.requested_scope == "audit_db"

    def test_check_denied_scope_required_but_none(self) -> None:
        gate = CapabilityGate()
        gate.declare("p1", [CapabilityRef(name="db.read", scope="credit_db")])
        with pytest.raises(CapabilityDeniedError):
            gate.check("p1", "db.read", None)

    def test_double_declare_rejected(self) -> None:
        gate = CapabilityGate()
        ref = CapabilityRef(name="db.read", scope="credit_db")
        gate.declare("p1", [ref])
        with pytest.raises(ValueError, match="already declared"):
            gate.declare("p1", [ref])

    def test_revoke_invalidates_grants(self) -> None:
        gate = CapabilityGate()
        gate.declare("p1", [CapabilityRef(name="db.read", scope="credit_db")])
        gate.check("p1", "db.read", "credit_db")
        gate.revoke("p1")
        with pytest.raises(CapabilityDeniedError):
            gate.check("p1", "db.read", "credit_db")

    def test_audit_callback_emits_granted(self) -> None:
        events: list[dict[str, Any]] = []
        gate = CapabilityGate(audit=events.append)
        gate.declare("p1", [CapabilityRef(name="db.read", scope="credit_db")])
        gate.check("p1", "db.read", "credit_db")
        assert events[-1]["outcome"] == "granted"
        assert events[-1]["plugin"] == "p1"

    def test_audit_callback_emits_denied(self) -> None:
        events: list[dict[str, Any]] = []
        gate = CapabilityGate(audit=events.append)
        with pytest.raises(CapabilityDeniedError):
            gate.check("p1", "db.read", "credit_db")
        assert events[-1]["outcome"] == "denied"

    def test_lru_eviction(self) -> None:
        gate = CapabilityGate(lru_size=2)
        gate.declare(
            "p1",
            [
                CapabilityRef(name="db.read", scope="credit_db"),
                CapabilityRef(name="net.outbound", scope="*.cbr.ru"),
                CapabilityRef(name="cache.read", scope="x:*"),
            ],
        )
        gate.check("p1", "db.read", "credit_db")
        gate.check("p1", "net.outbound", "api.cbr.ru")
        gate.check("p1", "cache.read", "x:1")
        # cache размер ≤ 2; первый запрос должен быть вытеснен,
        # но повторная проверка должна быть снова granted (re-validate).
        gate.check("p1", "db.read", "credit_db")  # no raise

    def test_glob_scope_grant(self) -> None:
        gate = CapabilityGate()
        gate.declare("p1", [CapabilityRef(name="net.outbound", scope="*.cbr.ru")])
        gate.check("p1", "net.outbound", "api.cbr.ru")
        with pytest.raises(CapabilityDeniedError):
            gate.check("p1", "net.outbound", "api.bank.local")

    def test_uri_scheme_grant(self) -> None:
        gate = CapabilityGate()
        gate.declare(
            "p1", [CapabilityRef(name="secrets.read", scope="vault://credit/*")]
        )
        gate.check("p1", "secrets.read", "vault://credit/api_key")
        with pytest.raises(CapabilityDeniedError):
            gate.check("p1", "secrets.read", "env://CREDIT_KEY")

    def test_declarations_returns_refs(self) -> None:
        gate = CapabilityGate()
        ref = CapabilityRef(name="db.read", scope="credit_db")
        gate.declare("p1", [ref])
        assert gate.declarations("p1") == (ref,)

    def test_unknown_capability_in_declare_raises(self) -> None:
        from src.core.security.capabilities import CapabilityNotFoundError

        gate = CapabilityGate()
        with pytest.raises(CapabilityNotFoundError):
            gate.declare("p1", [CapabilityRef(name="unknown.do", scope="x")])

    def test_scope_optional_capability(self) -> None:
        # capability с scope_required=False принимает любой scope.
        vocab = CapabilityVocabulary()
        vocab.register(
            CapabilityDef(
                name="public.ping", matcher=ExactAliasMatcher(), scope_required=False
            )
        )
        gate = CapabilityGate(vocabulary=vocab)
        gate.declare("p1", [CapabilityRef(name="public.ping")])
        gate.check("p1", "public.ping", None)
        gate.check("p1", "public.ping", "anything")


# ── check_capabilities_subset ─────────────────────────────────────────


class TestCheckCapabilitiesSubset:
    def test_route_covered_by_plugin(self) -> None:
        vocab = build_default_vocabulary()
        check_capabilities_subset(
            route="r1",
            route_caps=[CapabilityRef(name="db.read", scope="credit_db")],
            plugin_caps_by_name={
                "credit": (CapabilityRef(name="db.read", scope="credit_db"),)
            },
            vocabulary=vocab,
        )

    def test_route_not_covered(self) -> None:
        vocab = build_default_vocabulary()
        with pytest.raises(CapabilitySupersetError) as exc:
            check_capabilities_subset(
                route="r1",
                route_caps=[CapabilityRef(name="db.read", scope="credit_db")],
                plugin_caps_by_name={},
                vocabulary=vocab,
            )
        assert exc.value.route == "r1"
        assert exc.value.offending[0].name == "db.read"

    def test_route_glob_covered(self) -> None:
        vocab = build_default_vocabulary()
        check_capabilities_subset(
            route="r1",
            route_caps=[CapabilityRef(name="net.outbound", scope="api.cbr.ru")],
            plugin_caps_by_name={
                "p": (CapabilityRef(name="net.outbound", scope="*.cbr.ru"),)
            },
            vocabulary=vocab,
        )

    def test_public_capability_no_plugin_needed(self) -> None:
        vocab = build_default_vocabulary()
        vocab.register(
            CapabilityDef(
                name="public.ping",
                matcher=ExactAliasMatcher(),
                public=True,
                scope_required=False,
            )
        )
        check_capabilities_subset(
            route="r1",
            route_caps=[CapabilityRef(name="public.ping")],
            plugin_caps_by_name={},
            vocabulary=vocab,
        )

    def test_unknown_capability_offending(self) -> None:
        vocab = build_default_vocabulary()
        # capability не зарегистрирована — считается не покрытой.
        with pytest.raises(CapabilitySupersetError):
            check_capabilities_subset(
                route="r1",
                route_caps=[CapabilityRef(name="unknown.do", scope="x")],
                plugin_caps_by_name={
                    "p": (CapabilityRef(name="unknown.do", scope="x"),)
                },
                vocabulary=vocab,
            )

    def test_glob_does_not_match_subset(self) -> None:
        vocab = CapabilityVocabulary()
        vocab.register(CapabilityDef(name="net.outbound", matcher=GlobScopeMatcher()))
        with pytest.raises(CapabilitySupersetError):
            check_capabilities_subset(
                route="r1",
                route_caps=[CapabilityRef(name="net.outbound", scope="bad.host")],
                plugin_caps_by_name={
                    "p": (CapabilityRef(name="net.outbound", scope="*.cbr.ru"),)
                },
                vocabulary=vocab,
            )
