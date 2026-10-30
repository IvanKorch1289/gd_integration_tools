"""TDD: tools/dsl_export_schemas.py — экспорт JSON-Schema процессоров (ADR-0058).

Регресс C4 (ADR-0369): CLI экспортировал 0 схем, потому что реестр
``@processor`` наполняется только при импорте модулей процессоров.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class TestDslExportSchemas:
    def test_cli_exports_non_zero_schemas(self, tmp_path: Path) -> None:
        """CLI в свежем интерпретаторе обязан экспортировать схемы.

        Отдельный процесс — иначе тест зависит от того, импортировал ли
        кто-то пакет процессоров раньше (именно этим и был замаскирован
        дефект: 0 схем).
        """
        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [
                sys.executable,
                str(repo_root / "tools" / "dsl_export_schemas.py"),
                "--output",
                str(tmp_path),
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "Экспортировано 0" not in result.stdout, result.stdout

        schemas = sorted(tmp_path.glob("*.schema.json"))
        assert schemas, "CLI не экспортировал ни одной схемы"
        assert (tmp_path / "index.json").exists()

    def test_helper_populates_processor_registry(self) -> None:
        """Helper импортирует пакет процессоров → реестр наполняется."""
        from src.backend.dsl.registry.processor import get_processor_registry
        from tools.dsl_export_schemas import _ensure_processors_imported

        _ensure_processors_imported()
        assert len(get_processor_registry()) > 0

    def test_cli_does_not_crash_on_optional_dependencies(self, tmp_path: Path) -> None:
        """CLI не падает на optional-зависимостях (ImportError → код 1, не трейсбек)."""
        from tools.dsl_export_schemas import main

        exit_code = main(["--output", str(tmp_path)])
        assert exit_code in (0, 1)


class TestMakeSchemasTarget:
    """ADR-0399: ``make schemas`` публикует схемы процессоров в docs/."""

    def test_make_schemas_target_is_declared(self) -> None:
        """Цель ``schemas`` объявлена в ``make/codegen.mk``."""
        repo_root = Path(__file__).resolve().parents[3]
        codegen = (repo_root / "make" / "codegen.mk").read_text(encoding="utf-8")
        assert "\nschemas:" in codegen, "make/codegen.mk: нет цели 'schemas'"
        assert "tools/dsl_export_schemas.py" in codegen, (
            "цель schemas должна звать tools/dsl_export_schemas.py"
        )

    def test_export_creates_output_dir_with_valid_json(self, tmp_path: Path) -> None:
        """Экспорт создаёт каталог (включая вложенные) и пишет валидные JSON."""
        from tools.dsl_export_schemas import main

        target = tmp_path / "docs" / "reference" / "schemas" / "processors"
        assert not target.exists()

        assert main(["--output", str(target)]) == 0

        assert target.is_dir(), "каталог публикации схем не создан"
        files = sorted(target.glob("*.schema.json"))
        assert files, "не экспортировано ни одной схемы процессора"
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(payload, dict), f"{path.name}: не JSON-объект"
            assert "$schema" in payload, f"{path.name}: нет $schema"
            assert payload.get("type") == "object", f"{path.name}: не object-schema"

        index = json.loads((target / "index.json").read_text(encoding="utf-8"))
        assert index["processors"], "index.json пуст"
        assert len(index["processors"]) == len(files)
