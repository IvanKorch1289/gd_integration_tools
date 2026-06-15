# ruff: noqa: S101
"""Тесты CapabilityVocabulary (ADR-044)."""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities import (
    CapabilityDef,
    CapabilityNotFoundError,
    CapabilityRef,
    CapabilityVocabulary,
    ExactAliasMatcher,
    build_default_vocabulary,
)


class TestCapabilityVocabulary:
    def test_register_and_get(self) -> None:
        v = CapabilityVocabulary()
        v.register(CapabilityDef(name="my.do", matcher=ExactAliasMatcher()))
        assert v.has("my.do")
        assert v.get("my.do").name == "my.do"

    def test_double_register_rejected(self) -> None:
        v = CapabilityVocabulary()
        v.register(CapabilityDef(name="my.do", matcher=ExactAliasMatcher()))
        with pytest.raises(ValueError, match="already registered"):
            v.register(CapabilityDef(name="my.do", matcher=ExactAliasMatcher()))

    def test_alias_registration(self) -> None:
        v = CapabilityVocabulary()
        v.register(
            CapabilityDef(
                name="my.do", matcher=ExactAliasMatcher(), aliases=("legacy.do",)
            )
        )
        assert v.has("legacy.do")
        assert v.get("legacy.do").name == "my.do"

    def test_get_missing_raises(self) -> None:
        v = CapabilityVocabulary()
        with pytest.raises(CapabilityNotFoundError):
            v.get("nope.x")

    def test_validate_ref_scope_required(self) -> None:
        v = build_default_vocabulary()
        # db.read имеет scope_required=True по дефолту.
        v.validate_ref(CapabilityRef(name="db.read", scope="credit_db"))
        with pytest.raises(ValueError, match="requires explicit scope"):
            v.validate_ref(CapabilityRef(name="db.read"))

    def test_default_catalog_full(self) -> None:
        v = build_default_vocabulary()
        for name in (
            "db.read",
            "db.write",
            "secrets.read",
            "net.outbound",
            "net.inbound",
            "fs.read",
            "fs.write",
            "fs.create_new",
            "storage.read",
            "storage.write",
            "code.execute",
            "mq.publish",
            "mq.consume",
            "cache.read",
            "cache.write",
            "workflow.start",
            "workflow.signal",
            "llm.invoke",
        ):
            assert v.has(name), f"missing {name}"
        assert len(v.all()) == 43

    def test_fs_create_new_registered(self) -> None:
        """V15 R-V15-4: capability fs.create_new обязательна для AIFsFacade."""
        v = build_default_vocabulary()
        defn = v.get("fs.create_new")
        assert defn.scope_required is True
        assert "AI-workspaces" in defn.description

    def test_code_execute_registered(self) -> None:
        """V15 R-V15-4: capability code.execute обязательна для CodeSandbox."""
        v = build_default_vocabulary()
        defn = v.get("code.execute")
        assert defn.scope_required is True
        assert "sandbox" in defn.description.lower()

    def test_public_capabilities_subset(self) -> None:
        v = build_default_vocabulary()
        v.register(
            CapabilityDef(
                name="public.ping",
                matcher=ExactAliasMatcher(),
                public=True,
                scope_required=False,
            )
        )
        publics = v.public_capabilities()
        assert any(d.name == "public.ping" for d in publics)
