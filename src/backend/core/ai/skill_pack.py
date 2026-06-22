"""SkillPackSpec — декларативная спецификация skill pack (S29 W2).

План Agent DSL + Memory Orchestration Layer, Phase 6.

Skill pack — это named collection of skill references с optional
retrieval policy и post-processing. Позволяет группировать skills
для повторного использования и динамической привязки к агентам.

Декларация в plugin.toml::

    [[skill_pack]]
    id            = "credit_skills"
    description   = "Набор навыков для кредитной оценки"
    skills        = ["credit.score.calculate", "credit.check.rules", "credit.fetch.history"]
    retrieval_policy = "semantic"
    post_processing = "dedup"

См. также
---------
* :class:`SkillSpec` — :mod:`core.ai.skill_registry`.
* :class:`SkillInvokeProcessor` — :mod:`dsl.engine.processors.agent_dsl.skill_invoke`.
* :class:`BindSkillProcessor` — :mod:`dsl.engine.processors.agent_dsl.bind_skill`.
"""

from __future__ import annotations
from src.backend.core.logging import get_logger


from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = get_logger(__name__)


__all__ = ("SkillPackSpec",)


class SkillPackSpec(BaseModel):
    """Декларативная спецификация skill pack (S29 W2).

    Skill pack — это named collection of skill references с optional
    retrieval policy и post-processing для повторного использования.

    YAML::

        skill_packs:
          - id: "credit_skills"
            description: "Набор навыков для кредитной оценки"
            skills:
              - "credit.score.calculate"
              - "credit.check.rules"
            retrieval_policy: "semantic"
            post_processing: "dedup"

    Attributes:
        id: Уникальный идентификатор (``"credit_skills"``).
        description: Человекочитаемое описание.
        skills: Список skill_id references из :class:`SkillRegistry`.
        input_schema: Опц. JSON-Schema для входных данных pack.
        output_schema: Опц. JSON-Schema для выходных данных pack.
        retrieval_policy: Политика retrieval при вызове pack:

            * ``"recent"`` — последние N skills по времени использования;
            * ``"semantic"`` — семантический search по description;
            * ``"none"`` — все skills сразу.
        post_processing: Пост-обработка результата:

            * ``"dedup"`` — deduplicate результаты;
            * ``"rank"`` — rerank по confidence;
            * ``"none"`` — без изменений.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="Уникальный идентификатор.")
    description: str = Field(default="", description="Человекочитаемое описание.")
    skills: list[str] = Field(min_length=1, description="Список skill_id references.")
    input_schema: str | None = Field(
        default=None, description="JSON-Schema path для входных данных."
    )
    output_schema: str | None = Field(
        default=None, description="JSON-Schema path для выходных данных."
    )
    retrieval_policy: Literal["recent", "semantic", "none"] = "none"
    post_processing: Literal["dedup", "rank", "none"] = "none"
