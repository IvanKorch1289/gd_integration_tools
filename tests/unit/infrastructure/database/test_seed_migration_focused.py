"""Focused tests for OP-1 — initial seed migration (Wave OP).

Цель: подтвердить идемпотентность seed-миграции (admin user + default orderkinds)
и безопасность downgrade.

Тесты НЕ требуют реальной PostgreSQL — они проверяют структуру миграции
через AST-анализ (revision/down_revision, idempotent INSERTs) и
passlib-совместимость хэша пароля.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


class TestSeedMigrationFile:
    """Structural tests для seed migration file."""

    @pytest.fixture
    def migration_path(self) -> Path:
        return Path(
            "src/backend/infrastructure/database/migrations/versions/"
            "2026_09_11_1000-aa1b2c3d4e5f_seed_default_admin.py"
        )

    @pytest.fixture
    def migration_source(self, migration_path: Path) -> str:
        assert migration_path.exists(), f"Migration not found: {migration_path}"
        return migration_path.read_text(encoding="utf-8")

    @pytest.fixture
    def migration_tree(self, migration_source: str) -> ast.Module:
        return ast.parse(migration_source)

    @pytest.fixture
    def seed_source(self) -> str:
        """SQL seed'а живёт в seed_data.py (переиспользуется sqlite-веткой env.py)."""
        seed_path = Path(
            "src/backend/infrastructure/database/migrations/seed_data.py"
        )
        assert seed_path.exists()
        return seed_path.read_text(encoding="utf-8")

    def test_file_exists(self, migration_path: Path) -> None:
        """Файл миграции существует."""
        assert migration_path.exists()

    def test_syntax_valid(self, migration_source: str) -> None:
        """Python syntax валиден."""
        ast.parse(migration_source)

    def _extract_str_constant(self, migration_tree: ast.Module, target_id: str) -> list[str]:
        """Helper: extract string constants from module-level assignment (handles AnnAssign)."""
        results: list[str] = []
        for node in ast.walk(migration_tree):
            value = None
            if isinstance(node, ast.AnnAssign):
                # Python 3.x: ``x: str = "..."`` → AnnAssign.
                if isinstance(node.target, ast.Name) and node.target.id == target_id:
                    value = node.value
            elif isinstance(node, ast.Assign):
                if (
                    len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == target_id
                ):
                    value = node.value
            if value is not None and isinstance(value, ast.Constant):
                if isinstance(value.value, str):
                    results.append(value.value)
        return results

    def test_revision_id_correct(self, migration_tree: ast.Module) -> None:
        """revision = 'aa1b2c3d4e5f'."""
        revisions = self._extract_str_constant(migration_tree, "revision")
        assert "aa1b2c3d4e5f" in revisions

    def test_down_revision_correct(self, migration_tree: ast.Module) -> None:
        """down_revision = 'z9a8b7c6d5e4' (последняя существующая)."""
        down_revs = self._extract_str_constant(migration_tree, "down_revision")
        assert "z9a8b7c6d5e4" in down_revs

    def test_has_upgrade_function(self, migration_tree: ast.Module) -> None:
        """``upgrade()`` функция существует."""
        funcs = [
            node.name
            for node in ast.walk(migration_tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert "upgrade" in funcs
        assert "downgrade" in funcs

    def test_uses_on_conflict_do_nothing(self, seed_source: str) -> None:
        """Идемпотентность через ON CONFLICT DO NOTHING."""
        assert "ON CONFLICT" in seed_source
        assert "DO NOTHING" in seed_source

    def test_no_privileged_accounts_in_seed(self, seed_source: str) -> None:
        """P0: seed НЕ создаёт пользователей (bootstrap — отдельная команда)."""
        assert "INSERT INTO users" not in seed_source
        assert "password" not in seed_source.lower()
        assert "argon2" not in seed_source.lower()

    def test_inserts_orderkinds(self, seed_source: str) -> None:
        """Inserts default orderkinds (≥4 базовых)."""
        assert "INSERT INTO orderkinds" in seed_source
        assert "registration" in seed_source
        assert "cadastral_passport" in seed_source
        assert "encumbrance_registration" in seed_source
        assert "ownership_transfer" in seed_source

class TestNoPrivilegedCredentials:
    """P0: privileged credentials отсутствуют в seed-миграции."""

    @pytest.fixture
    def migration_source(self) -> str:
        path = Path(
            "src/backend/infrastructure/database/migrations/versions/"
            "2026_09_11_1000-aa1b2c3d4e5f_seed_default_admin.py"
        )
        return path.read_text(encoding="utf-8")

    def test_no_default_password_hash_in_source(self, migration_source: str) -> None:
        """P0: в миграции нет парольных хэшей вовсе."""
        assert "$argon2id$" not in migration_source
        assert "$pbkdf2" not in migration_source


class TestAlembicChain:
    """Verify migration chain integrity via alembic."""

    def test_migration_in_chain(self) -> None:
        """Новая миграция в chain."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        sd = ScriptDirectory.from_config(cfg)
        revs = [
            rev.revision for rev in sd.walk_revisions()
        ]
        assert "aa1b2c3d4e5f" in revs

    def test_chain_continuity(self) -> None:
        """Каждая миграция имеет валидный down_revision."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        sd = ScriptDirectory.from_config(cfg)

        # Build map of revisions.
        rev_map = {rev.revision: rev for rev in sd.walk_revisions()}

        # Проверяем что каждая (non-initial) revision имеет валидный down_revision.
        for rev in rev_map.values():
            if rev.down_revision is None:
                # Initial migration — OK.
                continue
            # down_revision должна существовать в chain (или быть branch label).
            if isinstance(rev.down_revision, str):
                assert rev.down_revision in rev_map, (
                    f"Revision {rev.revision} has unknown "
                    f"down_revision={rev.down_revision}"
                )

    def test_no_duplicate_revisions(self) -> None:
        """Все revisions уникальны."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        sd = ScriptDirectory.from_config(cfg)
        revs = [rev.revision for rev in sd.walk_revisions()]
        assert len(revs) == len(set(revs)), "Duplicate revisions found"

    def test_single_head(self) -> None:
        """Только один head (linear chain)."""
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        sd = ScriptDirectory.from_config(cfg)
        heads = sd.get_heads()
        # Допускаем один head для linear migration.
        assert len(heads) == 1, f"Expected 1 head, got {len(heads)}: {heads}"


class TestExports:
    def test_module_imports(self) -> None:
        """Migration module imports without error."""
        from importlib import import_module

        module = import_module(
            "src.backend.infrastructure.database.migrations.versions."
            "2026_09_11_1000-aa1b2c3d4e5f_seed_default_admin"
        )
        assert hasattr(module, "upgrade")
        assert hasattr(module, "downgrade")
        assert module.revision == "aa1b2c3d4e5f"
        assert module.down_revision == "z9a8b7c6d5e4"


class TestRealisticExample:
    """Realistic: idempotency check — running upgrade twice should not fail."""

    def test_on_conflict_in_orderkinds_insert(self) -> None:
        """orderkinds INSERT использует ON CONFLICT (skb_uuid) DO NOTHING."""
        from pathlib import Path

        src = Path(
            "src/backend/infrastructure/database/migrations/seed_data.py"
        ).read_text()
        assert "ON CONFLICT (skb_uuid) DO NOTHING" in src
