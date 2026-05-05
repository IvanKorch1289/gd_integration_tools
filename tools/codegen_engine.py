"""Wave 5.4 — общий codegen-движок поверх Jinja2.

Предоставляет минимальный API для рендеринга шаблонов из ``tools/templates/``
с пост-форматированием через ruff (автоматическая нормализация отступов,
импортов, trailing commas).

Использование::

    from tools.codegen_engine import CodegenEngine
    eng = CodegenEngine()
    code = eng.render("service.py.j2", name="customers", domain="core",
                      class_name="CustomersService", crud=True)
    eng.write(Path("src/backend/services/core/customers_service.py"), code)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

__all__ = ("CodegenEngine", "TEMPLATES_DIR")

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "tools" / "templates"

_logger = logging.getLogger("tools.codegen")


class CodegenEngine:
    """Минимальная Jinja2-обёртка с ruff-format пост-обработкой.

    Args:
        templates_dir: Путь к директории с ``*.j2``.
        format_on_write: Запускать ``ruff format`` после ``write``.
    """

    def __init__(
        self,
        *,
        templates_dir: Path | None = None,
        format_on_write: bool = True,
    ) -> None:
        """Инициализирует Jinja2-окружение из ``templates_dir``."""
        self._dir = templates_dir or TEMPLATES_DIR
        self._format = format_on_write
        # autoescape выключен намеренно: рендерим Python-код, не HTML.
        # XSS неприменим — output идёт в файлы исходников, не браузер.
        self._env = Environment(
            loader=FileSystemLoader(str(self._dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            autoescape=False,  # noqa: S701 — Python-codegen, не web-templating
        )

    def render(self, template: str, **context: Any) -> str:
        """Рендерит шаблон с переданным контекстом."""
        tmpl = self._env.get_template(template)
        return tmpl.render(**context)

    def write(self, path: Path, code: str, *, overwrite: bool = False) -> None:
        """Пишет ``code`` в ``path`` и (если ``format_on_write``) форматирует ruff'ом.

        Args:
            path: Целевой файл (родительская директория создаётся).
            code: Содержимое.
            overwrite: Разрешить перезапись существующего файла.

        Raises:
            FileExistsError: ``path`` существует и ``overwrite=False``.
        """
        if path.exists() and not overwrite:
            raise FileExistsError(f"Целевой файл уже существует: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        if self._format:
            self._format_with_ruff(path)

    @staticmethod
    def _format_with_ruff(path: Path) -> None:
        """Запускает ``ruff format`` + ``ruff check --fix`` на сгенерированном файле."""
        ruff_bin = shutil.which("ruff")
        if ruff_bin is None:
            _logger.debug("ruff не найден — пропускаю post-format")
            return
        # ruff_bin — абсолютный путь, аргумент path — Path-объект (контролируем).
        subprocess.run(  # noqa: S603 — codegen tool, args полностью контролируются
            [ruff_bin, "format", str(path)], check=False, capture_output=True
        )
        subprocess.run(  # noqa: S603
            [ruff_bin, "check", "--fix", str(path)], check=False, capture_output=True
        )
