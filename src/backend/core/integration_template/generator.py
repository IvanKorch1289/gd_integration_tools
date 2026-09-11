"""Template Generator — render template в target dir."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.backend.core.integration_template.catalog import (
    Template,
    TemplateCatalog,
    TemplateFile,
)

logger = logging.getLogger(__name__)

__all__ = ("GenerationResult", "TemplateGenerator", "get_template_generator")


@dataclass(slots=True)
class GeneratedFile:
    """Файл, созданный генератором."""

    path: str  # Relative to target_dir.
    absolute_path: str
    size_bytes: int
    executable: bool = False


@dataclass(slots=True)
class GenerationResult:
    """Результат template generation."""

    template_name: str
    target_dir: str
    files: list[GeneratedFile] = field(default_factory=list)
    missing_variables: list[str] = field(default_factory=list)
    success: bool = True


class TemplateGenerator:
    """Render Template → target dir с variable substitution."""

    def __init__(self) -> None:
        pass

    def generate(
        self,
        *,
        template: Template,
        variables: dict[str, Any],
        target_dir: str | Path,
        overwrite: bool = False,
    ) -> GenerationResult:
        """Generate files из template.

        Args:
            template: :class:`Template`.
            variables: dict {var_name: value}.
            target_dir: Destination directory.
            overwrite: Overwrite existing files (default: skip with error).

        Returns:
            :class:`GenerationResult` с созданными файлами.

        """
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        result = GenerationResult(
            template_name=template.name,
            target_dir=str(target),
        )

        # 1. Validate required variables.
        missing = [v for v in template.variables if v not in variables]
        if missing:
            result.success = False
            result.missing_variables = missing
            logger.warning(
                "TemplateGenerator: missing variables for %s: %s",
                template.name,
                missing,
            )
            return result

        # 2. Render + write files.
        for template_file in template.files:
            try:
                rendered = self._render(template_file.content, variables)
            except Exception as exc:
                result.success = False
                logger.error(
                    "TemplateGenerator: render failed for %s: %s",
                    template_file.path,
                    exc,
                )
                continue

            # Variable substitution in path too.
            file_path = self._render(template_file.path, variables)
            full_path = target / file_path

            # Check existing.
            if full_path.exists() and not overwrite:
                logger.warning(
                    "TemplateGenerator: file exists, skipping: %s", full_path
                )
                continue

            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(rendered, encoding="utf-8")

            if template_file.executable:
                full_path.chmod(0o755)

            result.files.append(
                GeneratedFile(
                    path=file_path,
                    absolute_path=str(full_path),
                    size_bytes=full_path.stat().st_size,
                    executable=template_file.executable,
                )
            )

        return result

    def _render(self, content: str, variables: dict[str, Any]) -> str:
        """Substitute ``{{var}}`` patterns."""
        def _replace(match: re.Match[str]) -> str:
            var_name = match.group(1).strip()
            if var_name not in variables:
                raise KeyError(f"Missing variable: {var_name}")
            return str(variables[var_name])

        return re.sub(r"\{\{\s*(\w+)\s*\}\}", _replace, content)


_generator: TemplateGenerator | None = None


def get_template_generator() -> TemplateGenerator:
    global _generator
    if _generator is None:
        _generator = TemplateGenerator()
    return _generator


def reset_template_generator() -> None:
    global _generator
    _generator = None
