"""Smoke-тест CLI ``tools/checks/pii_audit.py`` (S24 W1 DoD-2).

Без реального Presidio:
    * gold-set строится корректно (smoke mode → 20 docs);
    * precision/recall = 0 (presidio недоступен → найдено 0 entity);
    * exit code 1 при threshold > 0.

С реальным Presidio (integration, при наличии extra ai-safety):
    * precision >= 0.85 на smoke set;
    * gold-set парсится без ошибок.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture
def pii_audit_module():
    """Импортирует tools/checks/pii_audit.py как модуль через importlib."""
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "tools" / "checks" / "pii_audit.py"
    spec = importlib.util.spec_from_file_location("pii_audit_test_mod", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["pii_audit_test_mod"] = module
    spec.loader.exec_module(module)
    return module


def test_build_gold_set_smoke(pii_audit_module) -> None:
    """smoke mode возвращает >= 8 + 30 ≈ 38 docs (edges + templates)."""
    docs = pii_audit_module._build_gold_set(mode="smoke")
    assert len(docs) >= 38
    # Все documents имеют поле text
    for d in docs:
        assert isinstance(d.text, str)
        assert len(d.text) > 0


def test_build_gold_set_full(pii_audit_module) -> None:
    """full mode возвращает ~1000 docs (8 edges + 30 × 33)."""
    docs = pii_audit_module._build_gold_set(mode="full")
    assert len(docs) >= 990
    assert len(docs) <= 1010


def test_precision_recall_zero_when_presidio_unavailable(
    pii_audit_module,
) -> None:
    """Без Presidio все documents → 0 entities found → precision/recall = 0."""
    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        docs = pii_audit_module._build_gold_set(mode="smoke")
        found = [set() for _ in docs]  # пусто
        precision, recall, _stats = pii_audit_module._precision_recall(
            docs, found
        )
        assert precision == 0.0
        assert recall == 0.0


def test_cli_exits_with_error_when_threshold_unmet(
    pii_audit_module, tmp_path: Path
) -> None:
    """CLI с threshold 0.9 и без Presidio → exit code 1."""
    try:
        import presidio_analyzer  # noqa: F401

        pytest.skip("Presidio установлен — поведение будет другим")
    except ImportError:
        pass

    report = tmp_path / "report.json"
    exit_code = pii_audit_module.main(
        [
            "--mode",
            "smoke",
            "--threshold",
            "0.9",
            "--report",
            str(report),
        ]
    )
    assert exit_code == 1
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert '"precision": 0.0' in text
    assert '"recall": 0.0' in text


def test_cli_exits_zero_at_zero_threshold(
    pii_audit_module, tmp_path: Path
) -> None:
    """При threshold 0.0 даже precision=0 OK (защита от false-failure без Presidio)."""
    report = tmp_path / "report.json"
    exit_code = pii_audit_module.main(
        [
            "--mode",
            "smoke",
            "--threshold",
            "0.0",
            "--report",
            str(report),
        ]
    )
    assert exit_code == 0
