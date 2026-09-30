"""Unit-тесты AIFeedbackService + FeedbackDomainService (S38.4 DDD)."""

from __future__ import annotations

import pytest

from src.backend.core.domain.feedback import FeedbackDomainService
from src.backend.core.models.feedback import AIFeedbackDoc
from src.backend.core.repositories.feedback import FeedbackRepository
from src.backend.core.tenancy import TenantContext, set_tenant
from src.backend.services.ai.feedback.feedback_service import AIFeedbackService
from src.backend.services.ai.feedback.repository import InMemoryFeedbackRepository

pytestmark = pytest.mark.unit


@pytest.fixture
def repo() -> InMemoryFeedbackRepository:
    return InMemoryFeedbackRepository()


@pytest.fixture
def service(repo: FeedbackRepository) -> AIFeedbackService:
    return AIFeedbackService(repository=repo)


class TestFeedbackDomainService:
    def test_apply_label_updates_fields(self):
        doc = AIFeedbackDoc(query="q", response="r", agent_id="a1")
        result = FeedbackDomainService.apply_label(
            doc, label="positive", comment="ok", operator_id="op1"
        )
        assert result.feedback == "positive"
        assert result.feedback_comment == "ok"
        assert result.operator_id == "op1"
        assert result.labeled_at is not None

    def test_apply_label_none_doc_raises(self):
        with pytest.raises(ValueError, match="Cannot label a None document"):
            FeedbackDomainService.apply_label(None, label="positive")  # type: ignore[arg-type]

    def test_mark_indexed_updates_fields(self):
        doc = AIFeedbackDoc(query="q", response="r", agent_id="a1")
        result = FeedbackDomainService.mark_indexed(doc, rag_doc_id="rag_42")
        assert result.indexed_in_rag is True
        assert result.rag_doc_id == "rag_42"
        assert result.indexed_at is not None


class TestAIFeedbackService:
    @pytest.mark.asyncio
    async def test_save_response(self, service: AIFeedbackService):
        # P0 (audit a2bd6f294): get без tenant-контекста — fail-closed.
        set_tenant(TenantContext(tenant_id="tenant-t"))
        try:
            doc_id = await service.save_response(
                query="hello",
                response="hi",
                agent_id="agent_1",
                metadata={"tenant_id": "tenant-t"},
            )
            assert doc_id
            fetched = await service.get(doc_id)
            assert fetched is not None
            assert fetched.query == "hello"
            assert fetched.feedback is None
        finally:
            set_tenant(None)

    @pytest.mark.asyncio
    async def test_set_feedback(self, service: AIFeedbackService):
        set_tenant(TenantContext(tenant_id="tenant-t"))
        try:
            doc_id = await service.save_response(
                query="q",
                response="r",
                agent_id="a1",
                metadata={"tenant_id": "tenant-t"},
            )
        finally:
            set_tenant(None)
        updated = await service.set_feedback(
            doc_id=doc_id, label="negative", comment="wrong", operator_id="op1"
        )
        assert updated.feedback == "negative"
        assert updated.feedback_comment == "wrong"

    @pytest.mark.asyncio
    async def test_set_feedback_not_found(self, service: AIFeedbackService):
        with pytest.raises(KeyError):
            await service.set_feedback(doc_id="missing", label="positive")

    @pytest.mark.asyncio
    async def test_list_pending_and_labeled(self, service: AIFeedbackService):
        d1 = await service.save_response(query="q1", response="r1", agent_id="a1")
        d2 = await service.save_response(query="q2", response="r2", agent_id="a1")
        await service.set_feedback(doc_id=d2, label="positive")

        pending = await service.list_pending(agent_id="a1")
        assert len(pending) == 1
        assert pending[0].id == d1

        labeled = await service.list_labeled(agent_id="a1", label="positive")
        assert len(labeled) == 1
        assert labeled[0].id == d2

    @pytest.mark.asyncio
    async def test_stats(self, service: AIFeedbackService):
        await service.save_response(query="q1", response="r1", agent_id="a1")
        d2 = await service.save_response(query="q2", response="r2", agent_id="a1")
        await service.set_feedback(doc_id=d2, label="positive")

        stats = await service.stats()
        assert stats["pending"] == 1
        assert stats["positive"] == 1
        assert stats["negative"] == 0

    @pytest.mark.asyncio
    async def test_mark_indexed(self, service: AIFeedbackService):
        doc_id = await service.save_response(query="q", response="r", agent_id="a1")
        updated = await service.mark_indexed(doc_id, "rag_99")
        assert updated.indexed_in_rag is True
        assert updated.rag_doc_id == "rag_99"

    @pytest.mark.asyncio
    async def test_mark_indexed_not_found(self, service: AIFeedbackService):
        with pytest.raises(KeyError):
            await service.mark_indexed("missing", "rag_1")


class TestEmptyTenantFailClosed:
    """P0 (audit a2bd6f294): пустой tenant-контекст — fail-closed.

    Раньше: service.get при effective_tenant == "" уходил в
    repo.get(tenant_id=None) → без фильтра → cross-tenant чтение.
    """

    @pytest.mark.asyncio
    async def test_get_without_tenant_context_returns_none(
        self, service: AIFeedbackService
    ) -> None:
        from src.backend.core.tenancy import get_tenant_id

        set_tenant(TenantContext(tenant_id="tenant-b"))
        doc_id = await service.save_response(
            query="q", response="r", agent_id="a1", metadata={"tenant_id": "tenant-b"}
        )
        set_tenant(None)  # контекст снят: безконтекстный путь чтения

        assert get_tenant_id() == ""
        result = await service.get(doc_id)
        assert result is None, "fail-closed: чужой документ не виден без контекста"

    @pytest.mark.asyncio
    async def test_get_with_tenant_context_still_works(
        self, service: AIFeedbackService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.core.tenancy import set_tenant

        try:
            set_tenant(TenantContext(tenant_id="tenant-b"))
            doc_id = await service.save_response(
                query="q2",
                response="r2",
                agent_id="a1",
                metadata={"tenant_id": "tenant-b"},
            )
            result = await service.get(doc_id)
            assert result is not None
        finally:
            set_tenant(None)
