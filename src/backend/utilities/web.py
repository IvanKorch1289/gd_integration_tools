"""HTML/URL-helper'ы для tech-эндпоинтов."""

from fastapi.responses import HTMLResponse

__all__ = ("ensure_url_protocol", "generate_link_page")


def ensure_url_protocol(url: str) -> str:
    """Гарантирует протокол: добавляет `http://`, если ни http/https нет."""
    if not url.startswith(("http://", "https://")):
        return f"http://{url}"
    return url


def generate_link_page(url: str, description: str) -> HTMLResponse:
    """Минимальная HTML-страница с кликабельной ссылкой."""
    safe_url = ensure_url_protocol(url)
    return HTMLResponse(
        f"""
        <html>
            <body>
                <p>{description} link:
                    <a href="{safe_url}" target="_blank">{safe_url}</a>
                </p>
            </body>
        </html>
        """
    )
