"""Tests for K4APIClient logging improvements (Sprint 47 W4).

Verifies:
1. Backend failures логируются на уровне WARNING (не DEBUG).
2. ``rag_ingest_start`` использует index-based fallback ``file_{i}``
   для file-like объектов без ``.name`` атрибута (BytesIO, raw bytes).
3. Log message содержит method name + relevant context (args/kwargs).
"""

from __future__ import annotations

import logging
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from src.frontend.streamlit_app.api_clients.k4 import K4APIClient


class TestLoggingLevel:
    """Backend failures логируются на WARNING (production-visible)."""

    def test_get_rag_cache_stats_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        c = K4APIClient()
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", side_effect=Exception("boom")):
                c.get_rag_cache_stats()
        assert any(
            rec.levelno == logging.WARNING
            and "get_rag_cache_stats" in rec.message
            and "boom" in rec.message
            for rec in caplog.records
        )

    def test_flush_rag_cache_tier_logs_warning_with_tier(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        c = K4APIClient()
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", side_effect=Exception("boom")):
                c.flush_rag_cache_tier(tier="l1")
        assert any(
            rec.levelno == logging.WARNING
            and "flush_rag_cache_tier" in rec.message
            and "l1" in rec.message
            for rec in caplog.records
        )

    def test_litellm_gateway_stats_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        c = K4APIClient()
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", side_effect=Exception("boom")):
                c.litellm_gateway_stats()
        assert any(
            rec.levelno == logging.WARNING and "litellm_gateway_stats" in rec.message
            for rec in caplog.records
        )

    def test_rag_ingest_status_logs_warning_with_task_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        c = K4APIClient()
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", side_effect=Exception("boom")):
                c.rag_ingest_status("task-42")
        assert any(
            rec.levelno == logging.WARNING and "task-42" in rec.message
            for rec in caplog.records
        )

    def test_bulk_rag_ingest_logs_warning_with_doc_count(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        c = K4APIClient()
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", side_effect=Exception("boom")):
                c.bulk_rag_ingest(documents=[{"content": "x"}], collection="mycol")
        assert any(
            rec.levelno == logging.WARNING
            and "1 docs" in rec.message
            and "mycol" in rec.message
            for rec in caplog.records
        )

    def test_rag_ingest_start_logs_warning_with_collection(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        c = K4APIClient()
        f = BytesIO(b"data")
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", side_effect=Exception("boom")):
                c.rag_ingest_start(files=[f], collection="mycol")
        assert any(
            rec.levelno == logging.WARNING and "mycol" in rec.message
            for rec in caplog.records
        )

    def test_no_log_on_success(self, caplog: pytest.LogCaptureFixture) -> None:
        """Успешный path не должен логировать WARNING."""
        c = K4APIClient()
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", return_value={"ok": True}):
                c.get_rag_cache_stats()
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records == []


class TestFileFallback:
    """``rag_ingest_start`` — index-based fallback для files без .name."""

    def test_file_with_name_uses_name(self) -> None:
        c = K4APIClient()
        f = MagicMock()
        f.name = "doc.pdf"
        f.read.return_value = b"data"
        with patch.object(c, "_request", return_value={"task_id": "t1"}) as req:
            c.rag_ingest_start(files=[f])
        files_arg = req.call_args.kwargs["files"]
        assert files_arg == [("files", ("doc.pdf", b"data"))]

    def test_file_without_name_uses_index_fallback(self) -> None:
        c = K4APIClient()
        f = BytesIO(b"raw bytes")
        # BytesIO doesn't have .name attribute
        assert not hasattr(f, "name")
        with patch.object(c, "_request", return_value={"task_id": "t1"}) as req:
            c.rag_ingest_start(files=[f])
        files_arg = req.call_args.kwargs["files"]
        # Index-based fallback: "file_0"
        assert files_arg == [("files", ("file_0", b"raw bytes"))]

    def test_mixed_files_with_and_without_name(self) -> None:
        c = K4APIClient()
        f1 = MagicMock()
        f1.name = "doc1.txt"
        f1.read.return_value = b"data1"
        f2 = BytesIO(b"data2")  # no .name
        with patch.object(c, "_request", return_value={"task_id": "t1"}) as req:
            c.rag_ingest_start(files=[f1, f2])
        files_arg = req.call_args.kwargs["files"]
        # f1 uses "doc1.txt", f2 uses "file_1" (index)
        assert files_arg == [
            ("files", ("doc1.txt", b"data1")),
            ("files", ("file_1", b"data2")),
        ]

    def test_file_with_empty_name_uses_index_fallback(self) -> None:
        """File with .name="" (empty string) должен использовать fallback."""
        c = K4APIClient()
        f = MagicMock()
        f.name = ""  # empty string
        f.read.return_value = b"data"
        with patch.object(c, "_request", return_value={"task_id": "t1"}) as req:
            c.rag_ingest_start(files=[f])
        files_arg = req.call_args.kwargs["files"]
        # Empty string is falsy → fallback
        assert files_arg == [("files", ("file_0", b"data"))]


class TestLoggingOnHappyPath:
    """Успешный path не логирует WARNING (sanity check)."""

    @pytest.mark.parametrize(
        "method_name,call_args,call_kwargs",
        [
            ("get_rag_cache_stats", (), {}),
            ("flush_rag_cache_tier", (), {"tier": "l1"}),
            ("get_rag_invalidation_events", (), {"limit": 10}),
            ("litellm_gateway_stats", (), {}),
            ("list_embedding_providers", (), {}),
            ("rag_ingest_status", ("task-1",), {}),
            ("rag_search_preview", ("query",), {}),
        ],
    )
    def test_no_warning_on_success(
        self,
        caplog: pytest.LogCaptureFixture,
        method_name: str,
        call_args: tuple,
        call_kwargs: dict,
    ) -> None:
        c = K4APIClient()
        with caplog.at_level(logging.WARNING):
            with patch.object(c, "_request", return_value={"ok": True}):
                getattr(c, method_name)(*call_args, **call_kwargs)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [], (
            f"Method {method_name} logged warning on success: {warnings}"
        )
