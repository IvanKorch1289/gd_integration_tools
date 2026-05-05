"""Стартовая страница приложения.

Рендерит статический HTML из ``src/static/index.html``
с подстановкой динамических URL сервисов.
"""

from pathlib import Path

from starlette.responses import HTMLResponse

from src.core.config.settings import settings
from src.utilities.web import ensure_url_protocol

__all__ = ("root_page",)

_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


async def root_page() -> HTMLResponse:
    """Возвращает главную HTML-страницу.

    Читает ``index.html`` из статических файлов и подставляет
    динамические URL через JavaScript-инъекцию.

    Returns:
        ``HTMLResponse`` с главной страницей.
    """
    html_path = _STATIC_DIR / "index.html"

    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
    else:
        html = "<h1>GD Integration Tools</h1><p>index.html не найден</p>"

    def _safe_url(url: str | None) -> str:
        if not url:
            return "#"
        return ensure_url_protocol(url)

    urls_script = f"""
    <script>
    (function() {{
        var links = {{
            'link-logs': '{_safe_url(settings.logging.base_url)}',
            'link-storage': '{_safe_url(settings.storage.interface_endpoint)}',
            'link-queue': '{_safe_url(settings.queue.queue_ui_url)}'
        }};
        for (var id in links) {{
            var el = document.getElementById(id);
            if (el && links[id] !== '#') el.href = links[id];
        }}
    }})();
    </script>
    """

    html = html.replace("</body>", urls_script + "</body>")

    return HTMLResponse(content=html)
