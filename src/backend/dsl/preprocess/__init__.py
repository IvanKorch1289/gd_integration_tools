"""DSL preprocessors (S10 K3 W7): Jinja2 macros over YAML."""

from __future__ import annotations

from src.backend.dsl.preprocess.jinja_macros import has_jinja_syntax, render_macros

__all__ = ("has_jinja_syntax", "render_macros")
