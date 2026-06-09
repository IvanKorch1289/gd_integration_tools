"""Workflow Template Registry — Sprint 12 K3 W5.

Public API:

* :class:`WorkflowTemplate` — pydantic dataclass (name, description, tags,
  file_path, declaration).
* :class:`WorkflowTemplateRegistry`:
    - ``load_all()`` — сканирует ``src/backend/dsl/workflow/templates/*.yaml``;
    - ``get(name)`` — точный lookup;
    - ``search_semantic(query, top_k=5)`` — BGE-M3 поиск с fallback на
      rapidfuzz (rapidfuzz уже в зависимостях S10 K3 W5).

Lazy-import тяжёлых зависимостей:

* :mod:`sentence_transformers` — только при первом
  ``search_semantic`` если ``feature_flags.workflow_template_semantic_search``
  включён, иначе rapidfuzz.

ADR: Templates загружаются с feature-flag для сохранения backwards-compat:
если ``workflow_yaml_round_trip`` выключен, мы используем ``yaml.safe_load``
напрямую без Pydantic-валидации (для preview).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml as _yaml

from src.backend.core.logging import get_logger

__all__ = ("WorkflowTemplate", "WorkflowTemplateRegistry", "get_template_registry")

_logger = get_logger("services.workflows.template_registry")

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "dsl" / "workflow" / "templates"


@dataclass(frozen=True, slots=True)
class WorkflowTemplate:
    """Метаданные template + raw declaration dict (без Pydantic-валидации)."""

    name: str
    description: str
    tags: tuple[str, ...]
    file_path: str
    raw: dict[str, Any] = field(repr=False)

    @property
    def step_count(self) -> int:
        """Количество шагов в template."""
        return len(self.raw.get("steps", []))


def _extract_tags(description: str) -> tuple[str, ...]:
    """Парсит ``Template tags: a, b, c.`` из description."""
    if not description:
        return ()
    marker = "Template tags:"
    if marker not in description:
        return ()
    tail = description.split(marker, 1)[1].split(".", 1)[0]
    return tuple(t.strip() for t in tail.split(",") if t.strip())


class WorkflowTemplateRegistry:
    """Реестр workflow templates со scan + semantic search."""

    def __init__(self, templates_dir: Path | None = None) -> None:
        self._dir = templates_dir or _TEMPLATES_DIR
        self._loaded: list[WorkflowTemplate] | None = None

    def load_all(self) -> list[WorkflowTemplate]:
        """Сканирует ``*.workflow.yaml`` и собирает :class:`WorkflowTemplate`."""
        if self._loaded is not None:
            return self._loaded
        results: list[WorkflowTemplate] = []
        if not self._dir.exists():
            _logger.warning(
                "WorkflowTemplateRegistry: templates dir does not exist: %s", self._dir
            )
            self._loaded = results
            return results

        for yaml_path in sorted(self._dir.glob("*.workflow.yaml")):
            try:
                raw = _yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            except _yaml.YAMLError as exc:
                _logger.error(
                    "WorkflowTemplateRegistry: invalid YAML %s: %s", yaml_path, exc
                )
                continue

            if not isinstance(raw, dict):
                continue

            tmpl = WorkflowTemplate(
                name=str(raw.get("name", yaml_path.stem)),
                description=str(raw.get("description", "")),
                tags=_extract_tags(str(raw.get("description", ""))),
                file_path=str(yaml_path),
                raw=raw,
            )
            results.append(tmpl)

        self._loaded = results
        return results

    def get(self, name: str) -> WorkflowTemplate | None:
        """Возвращает template по точному имени или ``None``."""
        for tmpl in self.load_all():
            if tmpl.name == name:
                return tmpl
        return None

    def search_semantic(
        self, query: str, *, top_k: int = 5
    ) -> list[tuple[WorkflowTemplate, float]]:
        """Semantic search через BGE-M3 (если включён) или rapidfuzz fallback.

        Returns:
            Список ``(template, score)`` упорядоченный по убыванию score.
        """
        templates = self.load_all()
        if not templates or not query.strip():
            return []

        from src.backend.core.config.features import feature_flags

        if getattr(feature_flags, "workflow_template_semantic_search", False):
            try:
                scored = self._score_bge_m3(query, templates)
                if scored:
                    return sorted(scored, key=lambda x: -x[1])[:top_k]
            except ImportError as exc:
                _logger.warning("BGE-M3 unavailable (%s) — fallback to rapidfuzz", exc)

        return self._score_rapidfuzz(query, templates, top_k=top_k)

    @staticmethod
    def _score_rapidfuzz(
        query: str, templates: Sequence[WorkflowTemplate], *, top_k: int
    ) -> list[tuple[WorkflowTemplate, float]]:
        """Fallback fuzzy search через rapidfuzz или word-overlap."""
        try:
            from rapidfuzz import fuzz

            scored_rf: list[tuple[WorkflowTemplate, float]] = []
            for t in templates:
                text = f"{t.name} {t.description} {' '.join(t.tags)}"
                score = float(fuzz.partial_ratio(query.lower(), text.lower()))
                scored_rf.append((t, score))
            return sorted(scored_rf, key=lambda x: -x[1])[:top_k]
        except ImportError:
            pass

        query_words = {w for w in query.lower().split() if len(w) >= 3}
        scored: list[tuple[WorkflowTemplate, float]] = []
        for t in templates:
            text = f"{t.name} {t.description} {' '.join(t.tags)}".lower()
            text_words = set(text.replace("_", " ").split())
            overlap = len(query_words & text_words)
            substring_bonus = sum(2 for w in query_words if w in text)
            score = float(overlap + substring_bonus)
            scored.append((t, score))
        return sorted(scored, key=lambda x: -x[1])[:top_k]

    @staticmethod
    def _score_bge_m3(
        query: str, templates: Sequence[WorkflowTemplate]
    ) -> list[tuple[WorkflowTemplate, float]]:
        """Semantic search через sentence-transformers BGE-M3."""
        from sentence_transformers import SentenceTransformer, util

        model = SentenceTransformer("BAAI/bge-m3")
        q_emb = model.encode([query], convert_to_tensor=True)
        texts = [f"{t.name} {t.description} {' '.join(t.tags)}" for t in templates]
        t_embs = model.encode(texts, convert_to_tensor=True)
        sims = util.cos_sim(q_emb, t_embs)[0]
        return [(t, float(sims[i])) for i, t in enumerate(templates)]


@lru_cache(maxsize=1)
def get_template_registry() -> WorkflowTemplateRegistry:
    """Lazy singleton WorkflowTemplateRegistry."""
    return WorkflowTemplateRegistry()
