"""Unit-тесты :class:`AgentDefinition` + YAML-loader (S25-S27 Task 3 GAP G5).

Покрывает:

* Загрузка эталонного YAML из задачи (credit_risk_agent).
* Нормализация tools (single-key dict / explicit / plain-string).
* Валидация runtime / model.primary / version.
* Опциональные секции (memory / supervisor / rlm / stop_condition).
* :class:`AgentDefinitionLoadError` при невалидном YAML / Pydantic.
* :func:`load_agent_yaml_file` и :func:`load_agents_from_directory`.
* Защита от unsafe-YAML (``!!python/object`` запрещён).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from src.backend.dsl.loaders.agent_loader import (
    AgentDefinitionLoadError,
    load_agent_yaml,
    load_agent_yaml_file,
    load_agents_from_directory,
)
from src.backend.dsl.models.agent_definition import (
    AgentDefinition,
    MemoryLayerSpec,
    ModelRouterSpec,
    RLMSpec,
    StopConditionSpec,
    SupervisorSpec,
    ToolSpec,
)

CREDIT_RISK_AGENT_YAML = dedent(
    """\
    name: credit_risk_agent
    version: 1
    runtime: langgraph
    model:
      primary: openai/gpt-4o-mini
      fallback:
        - anthropic/claude-sonnet-4-6
        - local/llama-3-8b
    memory:
      episodic: { backend: postgres, ttl_hours: 168 }
      semantic: { backend: qdrant, ttl_hours: 720 }
    policy: credit_check_strict
    tools:
      - rag_query: { namespace: credit_docs, top_k: 5 }
      - sanitize_pii: {}
      - guardrails: { max_length: 10000 }
    rlm:
      enabled: true
      boost_factor: 0.1
    """
)


def test_loads_example_yaml_from_task() -> None:
    """Эталонный пример из Task 3 загружается без ошибок и валиден."""
    agent = load_agent_yaml(CREDIT_RISK_AGENT_YAML)

    assert isinstance(agent, AgentDefinition)
    assert agent.name == "credit_risk_agent"
    assert agent.version == 1
    assert agent.runtime == "langgraph"
    assert agent.policy == "credit_check_strict"

    assert agent.model.primary == "openai/gpt-4o-mini"
    assert agent.model.fallback == ["anthropic/claude-sonnet-4-6", "local/llama-3-8b"]
    assert agent.model.timeout_s == 30.0
    assert agent.model.retry_attempts == 2


def test_example_memory_section_parsed() -> None:
    """Memory.episodic / Memory.semantic парсятся как MemoryLayerSpec."""
    agent = load_agent_yaml(CREDIT_RISK_AGENT_YAML)
    assert agent.memory is not None
    assert agent.memory.scratch is None
    assert agent.memory.episodic == MemoryLayerSpec(backend="postgres", ttl_hours=168)
    assert agent.memory.semantic == MemoryLayerSpec(backend="qdrant", ttl_hours=720)


def test_example_tools_normalized_single_key_form() -> None:
    """YAML-форма ``- <name>: {config}`` нормализуется в ToolSpec."""
    agent = load_agent_yaml(CREDIT_RISK_AGENT_YAML)
    assert agent.tools == [
        ToolSpec(name="rag_query", config={"namespace": "credit_docs", "top_k": 5}),
        ToolSpec(name="sanitize_pii", config={}),
        ToolSpec(name="guardrails", config={"max_length": 10000}),
    ]


def test_example_rlm_section_parsed() -> None:
    """RLMSpec получает enabled=True и boost_factor=0.1 из YAML."""
    agent = load_agent_yaml(CREDIT_RISK_AGENT_YAML)
    assert agent.rlm is not None
    assert agent.rlm.enabled is True
    assert agent.rlm.boost_factor == pytest.approx(0.1)
    # default-значения остальных полей RLMSpec
    assert agent.rlm.threshold == pytest.approx(0.5)
    assert agent.rlm.consolidation_batch_size == 100
    assert agent.rlm.reindex_interval_hours == 24


def test_tools_explicit_form_supported() -> None:
    """Explicit-форма ``- name: ..., config: ...`` тоже принимается."""
    yaml_text = dedent(
        """\
        name: dual_agent
        runtime: pydanticai
        model: { primary: openai/gpt-4o-mini }
        tools:
          - name: rag_query
            config: { namespace: docs }
          - name: sanitize_pii
        """
    )
    agent = load_agent_yaml(yaml_text)
    assert agent.tools == [
        ToolSpec(name="rag_query", config={"namespace": "docs"}),
        ToolSpec(name="sanitize_pii", config={}),
    ]


def test_tools_plain_string_form_supported() -> None:
    """Plain-string-форма ``- sanitize_pii`` парсится с пустым config."""
    yaml_text = dedent(
        """\
        name: minimal
        runtime: dspy
        model: { primary: local/llama-3-8b }
        tools:
          - sanitize_pii
          - guardrails
        """
    )
    agent = load_agent_yaml(yaml_text)
    assert [t.name for t in agent.tools] == ["sanitize_pii", "guardrails"]
    assert all(t.config == {} for t in agent.tools)


def test_minimal_agent_only_required_fields() -> None:
    """Декларация с минимальным набором обязательных полей валидна."""
    yaml_text = dedent(
        """\
        name: minimal_agent
        runtime: dspy
        model:
          primary: local/llama-3-8b
        """
    )
    agent = load_agent_yaml(yaml_text)
    assert agent.name == "minimal_agent"
    assert agent.version == 1  # default
    assert agent.tools == []
    assert agent.memory is None
    assert agent.policy is None
    assert agent.supervisor is None
    assert agent.stop_condition is None
    assert agent.rlm is None


def test_runtime_must_be_one_of_three() -> None:
    """Допустимы только langgraph / pydanticai / dspy."""
    yaml_text = dedent(
        """\
        name: bad_runtime
        runtime: autogen
        model: { primary: openai/gpt-4o-mini }
        """
    )
    with pytest.raises(AgentDefinitionLoadError) as exc_info:
        load_agent_yaml(yaml_text)
    assert "runtime" in exc_info.value.reason.lower()


def test_model_primary_required() -> None:
    """Поле model.primary обязательно."""
    yaml_text = dedent(
        """\
        name: no_model
        runtime: langgraph
        model:
          fallback: [openai/gpt-4o-mini]
        """
    )
    with pytest.raises(AgentDefinitionLoadError) as exc_info:
        load_agent_yaml(yaml_text)
    assert "primary" in exc_info.value.reason.lower()


def test_extra_fields_rejected() -> None:
    """extra='forbid' блокирует неизвестные поля верхнего уровня."""
    yaml_text = dedent(
        """\
        name: with_extra
        runtime: langgraph
        model: { primary: openai/gpt-4o-mini }
        unknown_field: oops
        """
    )
    with pytest.raises(AgentDefinitionLoadError) as exc_info:
        load_agent_yaml(yaml_text)
    assert (
        "unknown_field" in exc_info.value.reason.lower()
        or "extra" in exc_info.value.reason.lower()
    )


def test_supervisor_only_for_langgraph() -> None:
    """Supervisor запрещён для pydanticai / dspy runtime."""
    yaml_text = dedent(
        """\
        name: bad_supervisor
        runtime: pydanticai
        model: { primary: openai/gpt-4o-mini }
        supervisor:
          type: flat
          agents: [sub_a, sub_b]
        """
    )
    with pytest.raises(AgentDefinitionLoadError) as exc_info:
        load_agent_yaml(yaml_text)
    assert "supervisor" in exc_info.value.reason.lower()


def test_supervisor_allowed_for_langgraph() -> None:
    """Supervisor с langgraph корректно валидируется."""
    yaml_text = dedent(
        """\
        name: with_supervisor
        runtime: langgraph
        model: { primary: openai/gpt-4o-mini }
        supervisor:
          type: hierarchical
          max_iterations: 5
          agents: [retrieval_agent, scoring_agent]
        """
    )
    agent = load_agent_yaml(yaml_text)
    assert agent.supervisor == SupervisorSpec(
        type="hierarchical",
        max_iterations=5,
        agents=["retrieval_agent", "scoring_agent"],
    )


def test_stop_condition_parsed() -> None:
    """StopConditionSpec парсится из YAML и применяет defaults."""
    yaml_text = dedent(
        """\
        name: capped_agent
        runtime: langgraph
        model: { primary: openai/gpt-4o-mini }
        stop_condition:
          max_steps: 15
          max_cost_usd: 1.25
          max_wall_time_s: 60
        """
    )
    agent = load_agent_yaml(yaml_text)
    assert agent.stop_condition == StopConditionSpec(
        max_steps=15, max_tool_calls=50, max_cost_usd=1.25, max_wall_time_s=60.0
    )


def test_invalid_yaml_syntax_raises() -> None:
    """Поломанный YAML → AgentDefinitionLoadError с понятным reason."""
    yaml_text = "name: broken\nruntime: [unterminated"
    with pytest.raises(AgentDefinitionLoadError) as exc_info:
        load_agent_yaml(yaml_text)
    assert "yaml" in exc_info.value.reason.lower()


def test_empty_yaml_raises() -> None:
    """Пустой YAML отвергается."""
    with pytest.raises(AgentDefinitionLoadError):
        load_agent_yaml("   \n")


def test_top_level_must_be_mapping() -> None:
    """YAML-список или скаляр на верхнем уровне отвергается."""
    with pytest.raises(AgentDefinitionLoadError) as exc_info:
        load_agent_yaml("- name: list_root\n  runtime: langgraph\n")
    assert "mapping" in exc_info.value.reason.lower()


def test_unsafe_yaml_python_object_rejected() -> None:
    """``!!python/object`` отвергается через safe_load."""
    yaml_text = dedent(
        """\
        name: !!python/object/new:os.system ["echo pwned"]
        runtime: langgraph
        model: { primary: openai/gpt-4o-mini }
        """
    )
    with pytest.raises(AgentDefinitionLoadError):
        load_agent_yaml(yaml_text)


def test_load_agent_yaml_file_round_trip(tmp_path: Path) -> None:
    """load_agent_yaml_file читает файл с UTF-8 и возвращает AgentDefinition."""
    path = tmp_path / "credit_risk_agent.agent.yaml"
    path.write_text(CREDIT_RISK_AGENT_YAML, encoding="utf-8")
    agent = load_agent_yaml_file(path)
    assert agent.name == "credit_risk_agent"


def test_load_agent_yaml_file_missing_path(tmp_path: Path) -> None:
    """Несуществующий файл → AgentDefinitionLoadError."""
    missing = tmp_path / "missing.agent.yaml"
    with pytest.raises(AgentDefinitionLoadError) as exc_info:
        load_agent_yaml_file(missing)
    assert (
        "read error" in exc_info.value.reason.lower()
        or "no such file" in exc_info.value.reason.lower()
    )


def test_load_agents_from_directory_returns_sorted(tmp_path: Path) -> None:
    """Директория сканируется рекурсивно, результат отсортирован по пути."""

    def _minimal(name: str) -> str:
        return dedent(
            f"""\
            name: {name}
            runtime: dspy
            model:
              primary: local/llama-3-8b
            """
        )

    (tmp_path / "z_agent.agent.yaml").write_text(_minimal("z_agent"), encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "a_agent.agent.yaml").write_text(_minimal("a_agent"), encoding="utf-8")

    agents = load_agents_from_directory(tmp_path)
    assert [a.name for a in agents] == ["a_agent", "z_agent"]


def test_load_agents_from_directory_missing_returns_empty(tmp_path: Path) -> None:
    """Несуществующая директория → пустой список без исключения."""
    assert load_agents_from_directory(tmp_path / "no_such_dir") == []


def test_model_router_defaults() -> None:
    """ModelRouterSpec без явного timeout_s / retry_attempts применяет defaults."""
    spec = ModelRouterSpec(primary="openai/gpt-4o-mini")
    assert spec.fallback == []
    assert spec.timeout_s == 30.0
    assert spec.retry_attempts == 2


def test_rlm_boost_factor_bounds() -> None:
    """boost_factor вне диапазона [0.0, 1.0] отвергается."""
    with pytest.raises(ValueError):
        RLMSpec(enabled=True, boost_factor=1.5)
    with pytest.raises(ValueError):
        RLMSpec(enabled=True, boost_factor=-0.1)
