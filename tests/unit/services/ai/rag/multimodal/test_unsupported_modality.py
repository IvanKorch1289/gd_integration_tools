"""D-AUDIT-10001: regression-тест UnsupportedModalityError (RAG-P2-005).

Бывший баг: video modality бросал bare NotImplementedError, который
нельзя было явно отличить от 'программист забыл реализовать
абстрактный метод' → caller не знал, как обрабатывать (501 vs 500
HTTP code; skip vs fail в batch ingest).

Фикс (cycle 100): named exception UnsupportedModalityError(NotImplementedError)
с атрибутами modality и planned_release. Callers могут явно ловить
и принимать решения (REST API → 501 Not Implemented, batch → skip
с WARNING).
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.rag.multimodal.pipeline import UnsupportedModalityError


def test_unsupported_modality_error_is_not_implemented_subclass() -> None:
    """UnsupportedModalityError — subclass of NotImplementedError
    (backward-compat: existing 'except NotImplementedError' continues
    to work).
    """
    err = UnsupportedModalityError("video", planned_release="S12")
    assert isinstance(err, NotImplementedError)
    assert err.modality == "video"
    assert err.planned_release == "S12"
    assert "video" in str(err)
    assert "S12" in str(err)


def test_unsupported_modality_error_without_planned_release() -> None:
    """Если planned_release не указан, exception всё равно работает."""
    err = UnsupportedModalityError("hologram")
    assert err.modality == "hologram"
    assert err.planned_release is None
    assert "hologram" in str(err)


def test_unsupported_modality_can_be_caught_specifically() -> None:
    """Caller может явно отличить UnsupportedModalityError от generic
    NotImplementedError через isinstance.
    """
    try:
        raise UnsupportedModalityError("video", planned_release="S12")
    except UnsupportedModalityError as exc:
        assert exc.modality == "video"
    except NotImplementedError:
        pytest.fail("UnsupportedModalityError should be caught specifically")


def test_unsupported_modality_backward_compat() -> None:
    """Bare 'except NotImplementedError' продолжает ловить (backward compat)."""
    try:
        raise UnsupportedModalityError("video", planned_release="S12")
    except NotImplementedError as exc:
        assert "video" in str(exc)
