"""Jinja2 macros для DSL YAML (S10 K3 W7, DSL-1.8).

Позволяет переиспользовать блоки в YAML routes/workflow через
``{% macro %}`` / ``{% include %}``. Препроцессор работает ДО парсинга
YAML — клиентский код получает чистый YAML без Jinja-конструкций.

Использование в DSL YAML::

    {% macro retry(attempts=3) %}
    policy:
      retry:
        attempts: {{ attempts }}
        backoff: exponential
    {% endmacro %}

    route_id: my_route
    steps:
      - http_call:
          url: https://api/x
          {{ retry(attempts=5) }}
      - http_call:
          url: https://api/y
          {{ retry() }}

API::

    from src.backend.dsl.preprocess.jinja_macros import render_macros

    rendered_yaml = render_macros(raw_yaml, search_path=Path("routes/"))

Безопасность:
* StrictUndefined — ловит опечатки имени макроса/переменной;
* autoescape выключен (генерится YAML, не HTML);
* {% include %} ищет файлы в ``search_path`` (default — текущая dir).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

__all__ = ("has_jinja_syntax", "render_macros")


def has_jinja_syntax(text: str) -> bool:
    """Возвращает ``True`` если в тексте есть Jinja-маркеры."""
    return "{%" in text or "{{" in text


def render_macros(
    yaml_text: str,
    *,
    search_path: Path | str | None = None,
    context: dict | None = None,
) -> str:
    """Прогоняет YAML через Jinja2 (macros + include).

    Args:
        yaml_text: исходный YAML с Jinja-конструкциями.
        search_path: директория для ``{% include %}``. Default — CWD.
        context: переменные, доступные в Jinja-шаблоне.

    Returns:
        Чистый YAML (Jinja-конструкции раскрыты).
    """
    if not has_jinja_syntax(yaml_text):
        return yaml_text

    loader_path = str(search_path or Path.cwd())
    # YAML output (не HTML); autoescape экранирует <, >, & и сломает
    # YAML (folded scalars, anchors). См. docstring модуля.
    env = Environment(  # nosec B701
        loader=FileSystemLoader(loader_path),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701  # internal macro preprocessing
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.from_string(yaml_text)
    return template.render(context or {})
