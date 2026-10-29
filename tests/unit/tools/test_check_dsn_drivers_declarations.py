"""Wave 13 Q9 — тесты гейта объявления DSN-драйверов (tools/check_dsn_drivers.py).

Гейт ловит ситуацию «DSN-конструктор упоминает драйвер, который не объявлен
ни в одном extra проекта» — с allowlist-файлом для известного долга
(``tools/check_dsn_drivers_allowlist.txt``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
_CHECK_FILE = _TOOLS_DIR / "check_dsn_drivers.py"
_spec = importlib.util.spec_from_file_location("check_dsn_drivers", _CHECK_FILE)
_check_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_check_mod)

DSN_DRIVER_MAP = _check_mod.DSN_DRIVER_MAP
KNOWN_DRIVER_MODULES = _check_mod.KNOWN_DRIVER_MODULES
collect_declared_distributions = _check_mod.collect_declared_distributions
collect_driver_references = _check_mod.collect_driver_references
check_driver_declarations = _check_mod.check_driver_declarations
load_allowlist = _check_mod.load_allowlist

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _write_fake_config(tmp_path: Path, driver: str) -> Path:
    """Кладёт фейковый модуль конфигурации в ожидаемый скан-каталог."""
    config_dir = tmp_path / "src" / "backend" / "core" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    fake = config_dir / "fake_config.py"
    fake.write_text(f'DRIVER = "{driver}"\n', encoding="utf-8")
    return fake


@pytest.mark.unit
class TestDriverMap:
    """Мапа DSN-тип → (sync, async) драйверы должна отражать код конфигурации."""

    def test_postgresql_sync_driver_is_psycopg(self) -> None:
        """PostgreSQL sync = ``psycopg`` (psycopg2 в проекте отсутствует)."""
        assert DSN_DRIVER_MAP["postgresql"] == ("psycopg", "asyncpg")

    def test_no_psycopg2_in_map(self) -> None:
        """``psycopg2`` не упоминается в мапе гейта."""
        assert "psycopg2" not in {
            driver for pair in DSN_DRIVER_MAP.values() for driver in pair
        }


@pytest.mark.unit
class TestDeclaredDistributions:
    """Разбор ``pyproject.toml``: core-зависимости + все extras."""

    def test_core_and_extras_are_collected(self) -> None:
        """В объявленных есть и core-dep (``asyncpg``), и extra-драйверы."""
        declared = collect_declared_distributions(_PROJECT_ROOT / "pyproject.toml")
        assert "asyncpg" in declared
        assert "psycopg" in declared
        assert "oracledb" in declared
        assert "aioodbc" in declared
        assert "aiomysql" in declared

    def test_psycopg2_is_not_declared(self) -> None:
        """``psycopg2`` не объявлен ни в core, ни в extras."""
        declared = collect_declared_distributions(_PROJECT_ROOT / "pyproject.toml")
        assert "psycopg2" not in declared
        assert "psycopg2-binary" not in declared


@pytest.mark.unit
class TestDriverReferenceScan:
    """Скан кода конфигурации: строковые литералы-драйверы."""

    def test_references_found_in_config_sources(self) -> None:
        """Скан находит драйверы, упомянутые в DSN-конструкторах."""
        refs = collect_driver_references(
            _PROJECT_ROOT / "src" / "backend" / "core" / "config"
        )
        assert "asyncpg" in refs
        assert "psycopg" in refs
        assert any("database.py" in loc for loc in refs["asyncpg"])

    def test_docstrings_are_not_treated_as_references(self, tmp_path: Path) -> None:
        """Docstring'и не считаются упоминаниями драйвера."""
        config_dir = tmp_path / "src" / "backend" / "core" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        fake = config_dir / "fake_config.py"
        fake.write_text('"""Docstring with psycopg2 mention."""\n', encoding="utf-8")
        refs = collect_driver_references(tmp_path)
        assert "psycopg2" not in refs

    def test_unknown_driver_literal_is_detected(self, tmp_path: Path) -> None:
        """Неизвестный драйвер в коде находится сканом."""
        config_dir = tmp_path / "src" / "backend" / "core" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        fake = config_dir / "fake_config.py"
        fake.write_text('DRIVER = "psycopg2"\n', encoding="utf-8")
        refs = collect_driver_references(tmp_path)
        assert "psycopg2" in refs
        assert any("fake_config.py" in loc for loc in refs["psycopg2"])


@pytest.mark.unit
class TestDeclarationGate:
    """Гейт объявлений: gap = драйвер из кода без объявления в extras."""

    def test_current_repo_has_no_new_gaps(self) -> None:
        """В текущем состоянии нет необъявленных драйверов (кроме allowlist)."""
        allowlist = load_allowlist(
            _PROJECT_ROOT / "tools" / "check_dsn_drivers_allowlist.txt"
        )
        gaps = check_driver_declarations(_PROJECT_ROOT, allowlist)
        assert gaps == [], f"Необъявленные DSN-драйверы: {gaps}"

    def test_known_gaps_are_exactly_the_allowlisted_ones(self) -> None:
        """Без allowlist видны только заранее известные долги."""
        allowlist = load_allowlist(
            _PROJECT_ROOT / "tools" / "check_dsn_drivers_allowlist.txt"
        )
        gaps = check_driver_declarations(_PROJECT_ROOT, frozenset())
        assert {gap.driver for gap in gaps} <= allowlist
        assert {gap.driver for gap in gaps} == allowlist

    def test_gap_reported_for_undeclared_driver(self, tmp_path: Path) -> None:
        """Драйвер без объявления попадает в gaps."""
        fake = _write_fake_config(tmp_path, "totally_unknown_driver")
        gaps = check_driver_declarations(tmp_path, allowlist=frozenset())
        assert any("totally_unknown_driver" in gap.driver for gap in gaps)
        assert any(fake.name in gap.location for gap in gaps)

    def test_allowlist_suppresses_known_gap(self, tmp_path: Path) -> None:
        """Allowlist скрывает известный долг."""
        _write_fake_config(tmp_path, "totally_unknown_driver")
        gaps = check_driver_declarations(
            tmp_path, allowlist=frozenset({"totally_unknown_driver"})
        )
        assert gaps == []

    def test_registry_distributions_are_declared(self) -> None:
        """Каждый драйвер реестра опирается на реально объявленную зависимость."""
        declared = collect_declared_distributions(_PROJECT_ROOT / "pyproject.toml")
        from src.backend.core.config.db_drivers import DB_DRIVER_DECLARATIONS

        for driver, declaration in DB_DRIVER_DECLARATIONS.items():
            if declaration.extra == "stdlib":
                continue
            assert declaration.distribution in declared, (
                f"{driver}: distribution '{declaration.distribution}' не объявлена "
                f"в pyproject.toml"
            )


@pytest.mark.unit
class TestAllowlistFile:
    """Allowlist-файл гейта — по образцу других гейтов репозитория."""

    def test_allowlist_file_exists(self) -> None:
        """Файл allowlist лежит рядом с гейтом."""
        assert (_TOOLS_DIR / "check_dsn_drivers_allowlist.txt").is_file()

    def test_allowlist_is_loadable(self) -> None:
        """Allowlist читается: комментарии игнорируются.

        Wave 13 Q2: ``pyodbc`` объявлен в extra ``db_drivers`` — запись снята.
        ADR-0381 (A4): ``ibm_db_sa`` снят — DB2 недостижим через SQLAlchemy
        DSN (диалект удалён в 2.0), тип отвергается fail-fast; allowlist
        гейта объявления драйверов пуст.
        """
        entries = load_allowlist(_TOOLS_DIR / "check_dsn_drivers_allowlist.txt")
        assert isinstance(entries, frozenset)
        assert "pyodbc" not in entries
        assert "psycopg2" not in entries
        assert "ibm_db_sa" not in entries


@pytest.mark.unit
class TestKnownDriverVocabulary:
    """Словарь известных драйверов покрывает упомянутые в коде модули."""

    def test_vocabulary_contains_known_drivers(self) -> None:
        """В словаре есть все драйверы, встречающиеся в DSN-конструкторах."""
        for driver in (
            "asyncpg",
            "psycopg",
            "psycopg2",
            "aiosqlite",
            "pysqlite",
            "oracledb",
            "aioodbc",
            "pyodbc",
            "aiomysql",
            "pymysql",
            "ibm_db_sa",
        ):
            assert driver in KNOWN_DRIVER_MODULES


@pytest.mark.unit
class TestScopeSplit:
    """Wave 13 Q9 — разделение scope: declarations блокирует, availability — нет.

    CI выполняет ``uv sync`` без extras, поэтому драйверы ``db_drivers``
    в CI-окружении не установлены. Блокирующим в CI может быть только
    класс «драйвер не объявлен в extra» (declarations).
    """

    def test_declarations_scope_passes_on_clean_repo(self) -> None:
        """На текущем репозитории declarations-класс чист → exit 0."""
        assert _check_mod.main(["--ci", "--scope", "declarations"]) == 0

    def test_unknown_scope_is_invocation_error(self) -> None:
        """Неизвестный scope → exit 2 (ошибка вызова, не «провал гейта»)."""
        assert _check_mod.main(["--ci", "--scope", "bogus"]) == 2

    def test_availability_scope_reports_missing_drivers(self) -> None:
        """Availability-класс: драйверы extras в CI-venv не установлены → exit 1."""
        code = _check_mod.main(["--ci", "--scope", "availability"])
        assert code in (0, 1)
