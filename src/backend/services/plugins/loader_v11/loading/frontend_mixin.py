from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Note: LoadedPluginV11 is also defined locally below (S52 W3 leftover from original imports_block)


from src.backend.core.logging import get_logger

_logger = get_logger("services.plugins.loader_v11")


class FrontendMixin:
    """frontend page mount/unmount + page prefix для LoadingMixin. S63 W1 extraction."""

    __slots__ = ()

    def _plugin_page_prefix(self, plugin_name: str) -> str:
        """Префикс для смонтированных файлов: ``plugin_<name>_``."""
        return f"plugin_{plugin_name}_"

    def _mount_frontend_pages(self, plugin_name: str, plugin_root: Path) -> int:
        """Монтирует ``extensions/<name>/frontend/pages/*.py`` через symlinks.

        Args:
            plugin_name: Имя плагина (для префикса в pages-каталоге).
            plugin_root: Путь к каталогу плагина (там где ``plugin.toml``).

        Returns:
            Количество смонтированных файлов (0 если папка отсутствует
            или streamlit_pages_dir не сконфигурирован).
        """
        if self._streamlit_pages_dir is None:
            return 0
        pages_src = plugin_root / "frontend" / "pages"
        if not pages_src.is_dir():
            return 0
        try:
            self._streamlit_pages_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _logger.warning(
                "Plugin %s: cannot create streamlit pages dir %s: %s",
                plugin_name,
                self._streamlit_pages_dir,
                exc,
            )
            return 0

        prefix = self._plugin_page_prefix(plugin_name)
        mounted = 0
        for src in sorted(pages_src.iterdir()):
            if not src.is_file() or src.suffix != ".py":
                continue
            dst = self._streamlit_pages_dir / f"{prefix}{src.name}"
            try:
                if dst.is_symlink() or dst.exists():
                    if dst.is_symlink() and dst.resolve() == src.resolve():
                        mounted += 1
                        continue
                    dst.unlink()
                dst.symlink_to(src.resolve())
            except OSError as exc:
                _logger.warning(
                    "Plugin %s: cannot symlink %s → %s: %s", plugin_name, src, dst, exc
                )
                continue
            mounted += 1
        return mounted

    def _unmount_frontend_pages(self, plugin_name: str) -> int:
        """Удаляет symlinks, смонтированные при load.

        Идемпотентно: при повторном вызове просто 0 удалений.
        """
        if self._streamlit_pages_dir is None or not self._streamlit_pages_dir.is_dir():
            return 0
        prefix = self._plugin_page_prefix(plugin_name)
        removed = 0
        for entry in self._streamlit_pages_dir.iterdir():
            if not entry.name.startswith(prefix):
                continue
            try:
                if entry.is_symlink() or entry.is_file():
                    entry.unlink()
                    removed += 1
            except OSError as exc:
                _logger.warning(
                    "Plugin %s: cannot remove %s: %s", plugin_name, entry, exc
                )
        return removed
