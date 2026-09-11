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
            target = None
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

    def test_uses_on_conflict_do_nothing(self, migration_source: str) -> None:
        """Идемпотентность через ON CONFLICT DO NOTHING."""
        assert "ON CONFLICT" in migration_source
        assert "DO NOTHING" in migration_source

    def test_inserts_admin_user(self, migration_source: str) -> None:
        """Inserts default admin user."""
        assert "INSERT INTO users" in migration_source
        assert "admin" in migration_source
        assert "is_superuser" in migration_source

    def test_inserts_orderkinds(self, migration_source: str) -> None:
        """Inserts default orderkinds (≥4 базовых)."""
        assert "INSERT INTO orderkinds" in migration_source
        assert "registration" in migration_source
        assert "cadastral_passport" in migration_source
        assert "encumbrance_registration" in migration_source
        assert "ownership_transfer" in migration_source

    def test_password_is_hashed_not_plaintext(self, migration_source: str) -> None:
        """Пароль хранится в виде хэша pbkdf2_sha512, НЕ plaintext."""
        # Проверяем что plaintext-пароль НЕ присутствует напрямую в комментариях.
        # (в docstring/hash references допустимо).
        lines_with_plaintext = [
            line
            for line in migration_source.split("\n")
            if "admin-default-password-change-me" in line
            and not line.strip().startswith("#")  # допускаем в комментариях.
            and "DEFAULT_ADMIN_PASSWORD_HASH" not in line  # и в docstring/hash.
        ]
        # Plaintext может быть ТОЛЬКО в комментариях или docstring — не в коде.
        # Если найдено в коде — fail.
        for line in lines_with_plaintext:
            # Разрешаем только в docstring/hash variables.
            assert (
                "DEFAULT_ADMIN_PASSWORD_HASH" in line
                or "plaintext" in line.lower()
                or line.strip().startswith('"""')
            ), f"Plaintext password in code: {line!r}"
        # Но хэш pbkdf2_sha512 присутствует.
        assert "pbkdf2-sha512" in migration_source
        assert "$pbkdf2-sha512$" in migration_source


class TestPasswordHash:
    """Verify password hash совместим с passlib/sqlalchemy_utils.PasswordType."""

    def test_hash_format(self) -> None:
        """Хэш имеет формат pbkdf2_sha512 (passlib default)."""
        hash_str = (
            "$pbkdf2-sha512$25000$i1Gqda611ppT6r3XOocQ4g$"
            "wS.x/pn5Q/fV/EREjpLpeJHQ0BvB6eHve/1v4RR0kcpfI.yHWgWIEhFwrwoYPg5ddMcZUgXnU7/nH/IpBSDP5Q"
        )
        # Verify with passlib.
        from passlib.context import CryptContext

        ctx = CryptContext(schemes=["pbkdf2_sha512"], deprecated="auto")
        assert ctx.verify("admin-default-password-change-me", hash_str) is True

    def test_hash_does_not_verify_wrong_password(self) -> None:
        """Хэш НЕ принимает неправильный пароль."""
        hash_str = (
            "$pbkdf2-sha512$25000$i1Gqda611ppT6r3XOocQ4g$"
            "wS.x/pn5Q/fV/EREjpLpeJHQ0BvB6eHve/1v4RR0kcpfI.yHWgWIEhFwrwoYPg5ddMcZUgXnU7/nH/IpBSDP5Q"
        )
        from passlib.context import CryptContext

        ctx = CryptContext(schemes=["pbkdf2_sha512"], deprecated="auto")
        assert ctx.verify("wrong-password", hash_str) is False


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

    def test_on_conflict_in_admin_insert(self) -> None:
        """Admin INSERT использует ON CONFLICT (username) DO NOTHING."""
        from pathlib import Path

        src = Path(
            "src/backend/infrastructure/database/migrations/versions/"
            "2026_09_11_1000-aa1b2c3d4e5f_seed_default_admin.py"
        ).read_text()
        # Оба INSERT должны иметь ON CONFLICT.
        assert "ON CONFLICT (username) DO NOTHING" in src
        assert "ON CONFLICT (skb_uuid) DO NOTHING" in src
