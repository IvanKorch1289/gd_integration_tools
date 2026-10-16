"""Unit tests for the debt/contract split of the layer gate (ADR-0348, option C).

Проверяют, что разделение baseline на два независимых класса состоялось и что
гейт по-прежнему честен: не падает ни на долге, ни на контрактах, но считает их
раздельно и ловит устаревшие записи в каждом классе независимо.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tools/ не является Python package — подключаем через path manipulation.
TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import check_layers


def test_debt_and_contract_are_disjoint() -> None:
    """Ни одна запись не может быть одновременно долгом и контрактом.

    Пересечение означало бы, что одна зависимость одновременно «осознанный
    контракт» и «долг, который надо снизить» — метрика перестала бы быть
    однозначной.
    """
    debt, contract = check_layers._load_baselines()

    assert debt, "debt baseline не должен быть пустым"
    assert contract, "contract baseline не должен быть пустым"
    assert not (debt & contract), (
        f"пересечение debt/contract: {sorted(debt & contract)}"
    )


def test_contract_entries_are_layered_facades() -> None:
    """В contract попадают только осознанные зависимости services -> dsl.

    Именно этот класс признан легитимным в ADR-0348: публичные фасады,
    намеренно отдающие DSL-примитивы. Всё остальное — реальный долг.
    """
    _, contract = check_layers._load_baselines()

    for entry in contract:
        _rel, layer, imported = entry.split("\t")
        assert layer == "services", f"неожиданный слой в contract: {entry}"
        assert imported.startswith("src.backend.dsl"), (
            f"неожиданный target в contract: {entry}"
        )


def test_both_files_exist() -> None:
    """Оба baseline-файла присутствуют в репозитории."""
    assert check_layers.ALLOWLIST_PATH.exists()
    assert check_layers.CONTRACT_PATH.exists()


def test_load_contract_tolerates_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Отсутствие contract-файла — не ошибка, а «контрактов нет».

    Иначе удаление файла обрушило бы гейт вместо того, чтобы честно
    показать нулевой остаток этого класса.
    """
    monkeypatch.setattr(check_layers, "CONTRACT_PATH", tmp_path / "absent.txt")

    assert check_layers._load_contract() == set()


def test_load_baselines_returns_two_sets(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_load_baselines`` возвращает пару, а не один объединённый набор."""
    monkeypatch.setattr(check_layers, "_load_allowlist", lambda: {"a\tb\tc"})
    monkeypatch.setattr(check_layers, "_load_contract", lambda: {"d\te\tf"})

    debt, contract = check_layers._load_baselines()

    assert debt == {"a\tb\tc"}
    assert contract == {"d\te\tf"}


def test_stale_detection_covers_contract_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись-призрак в contract считается устаревшей, а не проходит молча.

    Регрессия-guard: если бы contract не участвовал в baseline, его
    устаревшие записи могли бы накапливаться незаметно — и метрика
    «contract: N» показывала бы несуществующие зависимости.
    """
    allowlist_file = tmp_path / "allowlist.txt"
    allowlist_file.write_text("a.py\tservices\tx.mod\n", encoding="utf-8")
    contract_file = tmp_path / "contract.txt"
    contract_file.write_text(
        "ghost.py\tservices\tsrc.backend.dsl.gone\n", encoding="utf-8"
    )

    monkeypatch.setattr(check_layers, "ALLOWLIST_PATH", allowlist_file)
    monkeypatch.setattr(check_layers, "CONTRACT_PATH", contract_file)

    debt, contract = check_layers._load_baselines()
    current = {"a.py\tservices\tx.mod"}

    assert not (debt - current), "долг должен совпадать с текущим состоянием"
    assert (contract - current) == {"ghost.py\tservices\tsrc.backend.dsl.gone"}, (
        "запись-призрак в contract обязана попадать в stale"
    )
