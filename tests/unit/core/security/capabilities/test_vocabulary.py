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
            # Добавлены 2026-10-06 по решению владельца: роуты
            # hello_route / test_route_w1 / jupyter_hub_run объявляли эти
            # capability, но определений в vocabulary не было — из-за чего
            # их нельзя было ни сделать публичными, ни покрыть плагином.
            "audit.write",
            "jupyter.hub",
        ):
            assert v.has(name), f"missing {name}"
        assert len(v.all()) == 51  # 2026-10-06: +audit.write, +jupyter.hub (было 49)

    def test_net_capabilities_are_public(self) -> None:
        """Публичный набор: net.inbound, net.outbound + audit.write.

        Публичность снимает только declaration-time проверку манифеста роута.
        Рантайм-контроль (CapabilityGate.check через OutboundHttpClient и
        external_database_facade) public НЕ читает и scope по-прежнему
        сверяет — здесь это зафиксировано, чтобы регрессия была видна.

        ``audit.write`` сделан публичным 2026-10-06: audit-sink пишет
        append-only лог, не даёт доступа к данным, плагина-владельца не
        имеет, а шаг ``audit:`` нужен почти каждому маршруту.
        """
        v = build_default_vocabulary()
        public_names = {d.name for d in v.public_capabilities()}
        assert public_names == {"net.inbound", "net.outbound", "audit.write"}
        # Доменные и привилегированные capability остаются непубличными —
        # расширять набор молча нельзя.
        for name in ("db.read", "db.write", "ai.invoke", "secrets.read"):
            assert name not in public_names, f"{name} не должен быть публичным"

    def test_privileged_capabilities_are_not_public(self) -> None:
        """jupyter.hub НЕ публична: это удалённое выполнение кода.

        Отличие от audit.write принципиальное: запуск ноутбука на Jupyter Hub
        исполняет произвольный пользовательский код с сервисной учёткой.
        Публичность отдала бы эту операцию любому маршруту без провайдера,
        поэтому capability остаётся непубличной и покрывается только
        плагином через requires_plugins.
        """
        v = build_default_vocabulary()
        public_names = {d.name for d in v.public_capabilities()}
        assert v.has("jupyter.hub")
        assert "jupyter.hub" not in public_names, (
            "jupyter.hub — привилегированная capability, публичность запрещена"
        )

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
