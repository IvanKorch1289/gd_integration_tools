"""Coverage tests для 5 worst-covered api_clients (Sprint 46 W3).

Targets:
- feedback.py: 21.3% → 75%+
- rag.py: 21.8% → 75%+
- k4.py: 22.2% → 75%+
- flags.py: 27.8% → 75%+
- dsl_routes.py: 34.2% → 75%+

Подход: мокаем ``BaseAPIClient._request`` (или ``get``/``post``) через
``patch.object(c, "_request") as mock_req`` — mock capture в ``as`` clause,
assertions на самом ``mock_req`` (вне ``with`` блока ``c._request``
восстанавливается обратно в оригинальный method).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ============================================================
# FlagsClient tests
# ============================================================


class TestFlagsClient:
    """flags.py — feature flags list/toggle/overrides."""

    def test_get_flags_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        expected = [{"name": "x", "enabled": True}]
        with patch.object(c, "_request", return_value=expected) as req:
            result = c.get_flags()
        assert result == expected
        req.assert_called_once_with("GET", "/api/v1/admin/feature-flags")

    def test_get_flags_exception_returns_empty_list(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_flags() == []

    def test_toggle_flag_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            assert c.toggle_flag("my_flag", True) is True
        req.assert_called_once_with(
            "POST",
            "/api/v1/admin/feature-flags/my_flag/toggle",
            json={"enabled": True},
        )

    def test_toggle_flag_false(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            assert c.toggle_flag("my_flag", False) is True
        assert req.call_args.kwargs["json"] == {"enabled": False}

    def test_toggle_flag_exception_returns_false(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.toggle_flag("my_flag", True) is False

    def test_list_overrides_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        expected = {"global": {"x": True}, "per_tenant": {}}
        with patch.object(c, "_request", return_value=expected):
            assert c.list_overrides() == expected

    def test_list_overrides_exception_returns_empty_dict(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.list_overrides() == {}

    def test_set_override_with_tenant(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            result = c.set_override("flag_x", "value_y", tenant_id="t1", actor="admin")
        assert result == {"ok": True}
        req.assert_called_once_with(
            "PUT",
            "/api/v1/admin/feature-flags/flag_x",
            json={"value": "value_y", "tenant_id": "t1", "actor": "admin"},
        )

    def test_set_override_without_tenant(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            c.set_override("flag_x", "value_y")
        assert req.call_args.kwargs["json"]["tenant_id"] is None
        assert req.call_args.kwargs["json"]["actor"] == "ui"

    def test_set_override_exception_returns_none(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.set_override("x", 1) is None

    def test_clear_override_with_tenant(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            result = c.clear_override("flag_x", tenant_id="t1")
        assert result == {"ok": True}
        req.assert_called_once_with(
            "DELETE",
            "/api/v1/admin/feature-flags/flag_x",
            params={"actor": "ui", "tenant_id": "t1"},
        )

    def test_clear_override_without_tenant(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            c.clear_override("flag_x")
        assert req.call_args.kwargs["params"] == {"actor": "ui"}

    def test_clear_override_exception_returns_none(self) -> None:
        from src.frontend.streamlit_app.api_clients.flags import FlagsClient

        c = FlagsClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.clear_override("x") is None


# ============================================================
# FeedbackClient tests
# ============================================================


class TestFeedbackClient:
    """feedback.py — AI feedback (pending/labeled/stats/label/index-to-rag)."""

    def test_list_feedback_pending_defaults(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={"items": []}) as req:
            result = c.list_feedback_pending()
        assert result == {"items": []}
        req.assert_called_once_with(
            "GET",
            "/api/v1/ai/feedback/pending",
            params={"limit": 50, "offset": 0},
        )

    def test_list_feedback_pending_with_agent_id(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.list_feedback_pending(agent_id="agent_42", limit=10, offset=20)
        req.assert_called_once_with(
            "GET",
            "/api/v1/ai/feedback/pending",
            params={"limit": 10, "offset": 20, "agent_id": "agent_42"},
        )

    def test_list_feedback_labeled_all_filters(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.list_feedback_labeled(
                label="good", agent_id="a1", indexed_in_rag=True, limit=20, offset=5
            )
        req.assert_called_once_with(
            "GET",
            "/api/v1/ai/feedback/labeled",
            params={
                "limit": 20,
                "offset": 5,
                "label": "good",
                "agent_id": "a1",
                "indexed_in_rag": "true",
            },
        )

    def test_list_feedback_labeled_indexed_in_rag_false(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.list_feedback_labeled(indexed_in_rag=False)
        req.assert_called_once_with(
            "GET",
            "/api/v1/ai/feedback/labeled",
            params={"limit": 100, "offset": 0, "indexed_in_rag": "false"},
        )

    def test_list_feedback_labeled_no_filters(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.list_feedback_labeled()
        req.assert_called_once_with(
            "GET",
            "/api/v1/ai/feedback/labeled",
            params={"limit": 100, "offset": 0},
        )

    def test_get_feedback_stats(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={"pending": 5, "labeled": 100}) as req:
            result = c.get_feedback_stats()
        assert result == {"pending": 5, "labeled": 100}
        req.assert_called_once_with("GET", "/api/v1/ai/feedback/stats")

    def test_label_feedback_minimal(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            c.label_feedback("doc_1", label="good")
        req.assert_called_once_with(
            "POST",
            "/api/v1/ai/feedback/doc_1/label",
            json={"label": "good"},
        )

    def test_label_feedback_full(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.label_feedback(
                "doc_1", label="bad", comment="needs work", operator_id="op_1"
            )
        req.assert_called_once_with(
            "POST",
            "/api/v1/ai/feedback/doc_1/label",
            json={"label": "bad", "comment": "needs work", "operator_id": "op_1"},
        )

    def test_index_feedback_to_rag_defaults(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={"indexed": 50}) as req:
            result = c.index_feedback_to_rag()
        assert result == {"indexed": 50}
        req.assert_called_once_with(
            "POST",
            "/api/v1/ai/feedback/index-to-rag",
            json={"limit": 100},
        )

    def test_index_feedback_to_rag_with_agent_id(self) -> None:
        from src.frontend.streamlit_app.api_clients.feedback import FeedbackClient

        c = FeedbackClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.index_feedback_to_rag(agent_id="a1", limit=25)
        req.assert_called_once_with(
            "POST",
            "/api/v1/ai/feedback/index-to-rag",
            json={"limit": 25, "agent_id": "a1"},
        )


# ============================================================
# DSLRoutesClient tests
# ============================================================


class TestDSLRoutesClient:
    """dsl_routes.py — YAMLStore CRUD + validate + diff."""

    def test_get_routes(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        expected = [{"id": "r1"}, {"id": "r2"}]
        with patch.object(c, "_request", return_value=expected) as req:
            assert c.get_routes() == expected
        req.assert_called_once_with("GET", "/api/v1/admin/routes")

    def test_list_dsl_routes_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value=["r1", "r2"]):
            assert c.list_dsl_routes() == ["r1", "r2"]

    def test_list_dsl_routes_non_list_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value={"unexpected": "dict"}):
            assert c.list_dsl_routes() == []

    def test_list_dsl_routes_exception_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.list_dsl_routes() == []

    def test_get_dsl_route_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value={"yaml": "..."}) as req:
            result = c.get_dsl_route("route_42")
        assert result == {"yaml": "..."}
        req.assert_called_once_with("GET", "/api/v1/admin/dsl-routes/route_42")

    def test_get_dsl_route_exception_returns_none(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_dsl_route("missing") is None

    def test_create_dsl_route(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value={"id": "new_route"}) as req:
            result = c.create_dsl_route("yaml: content")
        assert result == {"id": "new_route"}
        req.assert_called_once_with(
            "POST", "/api/v1/admin/dsl-routes", json={"yaml": "yaml: content"}
        )

    def test_update_dsl_route(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            result = c.update_dsl_route("r1", "new_yaml")
        assert result == {"ok": True}
        req.assert_called_once_with(
            "PUT",
            "/api/v1/admin/dsl-routes/r1",
            json={"yaml": "new_yaml"},
        )

    def test_delete_dsl_route_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value={"ok": True}) as req:
            assert c.delete_dsl_route("r1") is True
        req.assert_called_once_with("DELETE", "/api/v1/admin/dsl-routes/r1")

    def test_delete_dsl_route_exception_returns_false(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.delete_dsl_route("missing") is False

    def test_validate_dsl_route_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value={"valid": True, "errors": []}) as req:
            result = c.validate_dsl_route("yaml: x")
        assert result == {"valid": True, "errors": []}
        req.assert_called_once_with(
            "POST",
            "/api/v1/admin/dsl-routes/validate",
            json={"yaml": "yaml: x"},
        )

    def test_validate_dsl_route_exception_returns_invalid(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", side_effect=Exception("syntax error")):
            result = c.validate_dsl_route("bad_yaml")
        assert result["valid"] is False
        assert "syntax error" in result["error"]

    def test_diff_dsl_route_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", return_value={"diff": "..."}) as req:
            result = c.diff_dsl_route("r1", "new_yaml")
        assert result == {"diff": "..."}
        req.assert_called_once_with(
            "POST",
            "/api/v1/admin/dsl-routes/r1/diff",
            json={"yaml": "new_yaml"},
        )

    def test_diff_dsl_route_exception_returns_none(self) -> None:
        from src.frontend.streamlit_app.api_clients.dsl_routes import DSLRoutesClient

        c = DSLRoutesClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.diff_dsl_route("r1", "x") is None


# ============================================================
# RAGClient tests
# ============================================================


class TestRAGClient:
    """rag.py — RAG stats/search/upload/augment + multipart helper."""

    def test_get_stats_no_collection(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "get", return_value={"docs": 100}) as get:
            result = c.get_stats()
        assert result == {"docs": 100}
        get.assert_called_once_with("/api/v1/rag/stats", params={})

    def test_get_stats_with_collection(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "get", return_value={"docs": 50}) as get:
            result = c.get_stats(collection="my_col")
        assert result == {"docs": 50}
        get.assert_called_once_with("/api/v1/rag/stats", params={"collection": "my_col"})

    def test_get_stats_non_dict_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "get", return_value="unexpected_string"):
            assert c.get_stats() == {}

    def test_get_stats_exception_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "get", side_effect=Exception("boom")):
            assert c.get_stats() == {}

    def test_search_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "post", return_value={"results": []}) as post:
            result = c.search("hello", top_k=3)
        assert result == {"results": []}
        post.assert_called_once_with(
            "/api/v1/rag/search", json={"query": "hello", "top_k": 3}
        )

    def test_search_with_namespace(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "post", return_value={}) as post:
            c.search("q", top_k=10, namespace="ns1")
        post.assert_called_once_with(
            "/api/v1/rag/search", json={"query": "q", "top_k": 10, "namespace": "ns1"}
        )

    def test_search_exception_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "post", side_effect=Exception("boom")):
            assert c.search("q") == {}

    def test_upload_minimal(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "_multipart_post", return_value={"id": "doc_1"}) as mp:
            result = c.upload(b"file bytes", "test.txt", "text/plain")
        assert result == {"id": "doc_1"}
        # _multipart_post is called with kwargs
        assert mp.call_args.kwargs["files"] == {
            "file": ("test.txt", b"file bytes", "text/plain")
        }
        assert mp.call_args.kwargs["data"] == {"namespace": "default"}

    def test_upload_with_metadata(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "_multipart_post", return_value={}) as mp:
            c.upload(
                b"data", "doc.pdf", "application/pdf", namespace="ns", metadata_json='{"k":1}'
            )
        assert mp.call_args.kwargs["data"] == {
            "namespace": "ns",
            "metadata_json": '{"k":1}',
        }

    def test_upload_exception_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "_multipart_post", side_effect=Exception("boom")):
            assert c.upload(b"x", "x.txt", "text/plain") == {}

    def test_augment_happy_path(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "post", return_value={"augmented": True}) as post:
            result = c.augment("query")
        assert result == {"augmented": True}
        post.assert_called_once_with(
            "/api/v1/rag/augment", json={"query": "query", "top_k": 5}
        )

    def test_augment_with_namespace(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "post", return_value={}) as post:
            c.augment("q", namespace="ns", top_k=10)
        post.assert_called_once_with(
            "/api/v1/rag/augment", json={"query": "q", "top_k": 10, "namespace": "ns"}
        )

    def test_augment_exception_returns_empty(self) -> None:
        from src.frontend.streamlit_app.api_clients.rag import RAGClient

        c = RAGClient()
        with patch.object(c, "post", side_effect=Exception("boom")):
            assert c.augment("q") == {}


# ============================================================
# K4APIClient tests
# ============================================================


class TestK4APIClient:
    """k4.py — RAG cache + ingest + LiteLLM gateway + embedding registry.

    Note: K4APIClient extends APIClient (not BaseAPIClient напрямую), и
    APIClient.__init__ не принимает max_retries. Используем defaults.
    """

    def test_get_rag_cache_stats_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value={"l1": 100, "l2": 50}) as req:
            result = c.get_rag_cache_stats()
        assert result == {"l1": 100, "l2": 50}
        req.assert_called_once_with("GET", "/api/v1/admin/rag-cache/stats")

    def test_get_rag_cache_stats_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_rag_cache_stats() == {}

    def test_flush_rag_cache_tier_no_tier(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value={"flushed": 10}) as req:
            result = c.flush_rag_cache_tier()
        assert result == {"flushed": 10}
        req.assert_called_once_with(
            "POST", "/api/v1/admin/rag-cache/flush", params={}
        )

    def test_flush_rag_cache_tier_with_tier(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value={}) as req:
            c.flush_rag_cache_tier(tier="l1")
        req.assert_called_once_with(
            "POST", "/api/v1/admin/rag-cache/flush", params={"tier": "l1"}
        )

    def test_flush_rag_cache_tier_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.flush_rag_cache_tier("l1") == {}

    def test_get_rag_invalidation_events_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value=[{"event": "x"}]) as req:
            result = c.get_rag_invalidation_events()
        assert result == [{"event": "x"}]
        req.assert_called_once_with(
            "GET", "/api/v1/admin/rag-cache/events", params={"limit": 50}
        )

    def test_get_rag_invalidation_events_with_limit(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value=[]) as req:
            c.get_rag_invalidation_events(limit=100)
        req.assert_called_once_with(
            "GET", "/api/v1/admin/rag-cache/events", params={"limit": 100}
        )

    def test_get_rag_invalidation_events_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.get_rag_invalidation_events() == []

    def test_litellm_gateway_stats_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value={"requests": 1000}) as req:
            result = c.litellm_gateway_stats()
        assert result == {"requests": 1000}
        req.assert_called_once_with("GET", "/api/v1/admin/litellm-gateway/stats")

    def test_litellm_gateway_stats_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.litellm_gateway_stats() == {}

    def test_list_embedding_providers_list(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value=["openai", "cohere"]) as req:
            result = c.list_embedding_providers()
        assert result == ["openai", "cohere"]
        req.assert_called_once_with("GET", "/api/v1/admin/embedding-providers")

    def test_list_embedding_providers_dict(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value={"providers": ["a", "b"]}):
            assert c.list_embedding_providers() == ["a", "b"]

    def test_list_embedding_providers_dict_no_providers_key(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value={"other": "key"}):
            assert c.list_embedding_providers() == []

    def test_list_embedding_providers_unexpected_type(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value=42):
            assert c.list_embedding_providers() == []

    def test_list_embedding_providers_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.list_embedding_providers() == []

    def test_rag_ingest_start_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        # Mock file-like objects with .name and .read
        f1 = MagicMock()
        f1.name = "doc1.txt"
        f1.read.return_value = b"content1"
        with patch.object(c, "_request", return_value={"task_id": "t1"}) as req:
            result = c.rag_ingest_start(files=[f1], collection="mycol")
        assert result == {"task_id": "t1"}
        assert req.call_args.args[0] == "POST"
        assert req.call_args.args[1] == "/api/v1/rag/ingest/start"
        assert req.call_args.kwargs["files"] == [("files", ("doc1.txt", b"content1"))]
        assert req.call_args.kwargs["data"] == {"collection": "mycol"}

    def test_rag_ingest_start_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            result = c.rag_ingest_start(files=[])
        assert result["task_id"] is None
        assert "boom" in result["error"]

    def test_rag_ingest_status_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value={"status": "running"}) as req:
            result = c.rag_ingest_status("task_42")
        assert result == {"status": "running"}
        req.assert_called_once_with("GET", "/api/v1/rag/ingest/status/task_42")

    def test_rag_ingest_status_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.rag_ingest_status("t1") == {}

    def test_rag_search_preview_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", return_value=[{"doc": "x"}]) as req:
            result = c.rag_search_preview("query", top_k=3)
        assert result == [{"doc": "x"}]
        req.assert_called_once_with(
            "GET", "/api/v1/rag/search", params={"query": "query", "top_k": 3}
        )

    def test_rag_search_preview_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            assert c.rag_search_preview("q") == []

    def test_bulk_rag_ingest_happy(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        docs = [{"content": "a", "metadata": {}}, {"content": "b", "metadata": {}}]
        with patch.object(c, "_request", return_value={"task_id": "t1"}) as req:
            result = c.bulk_rag_ingest(documents=docs, collection="mycol")
        assert result == {"task_id": "t1"}
        req.assert_called_once_with(
            "POST",
            "/api/v1/rag/bulk-ingest",
            json={"documents": docs, "collection": "mycol"},
        )

    def test_bulk_rag_ingest_exception(self) -> None:
        from src.frontend.streamlit_app.api_clients.k4 import K4APIClient

        c = K4APIClient()
        with patch.object(c, "_request", side_effect=Exception("boom")):
            result = c.bulk_rag_ingest(documents=[])
        assert result["task_id"] is None
        assert "boom" in result["error"]
