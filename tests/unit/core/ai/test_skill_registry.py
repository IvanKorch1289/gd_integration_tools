"""Unit-тесты :class:`SkillRegistry` (V11.2, ADR-NEW-22) — полное покрытие ``invoke``.

Дополняет ``test_skill_registry_scaffold.py`` (smoke) и покрывает:

* ``from_toml_manifest`` с пустой секцией ``[[skill]] = None`` (line 157);
* ``from_toml_manifest`` с отсутствующим required-полем → ``ValueError``;
* ``from_python_decorator`` — NotImplementedError (scaffold);
* ``invoke`` — успешный путь для sync- и async-handler'ов;
* ``invoke`` — все error paths: unknown skill, malformed handler,
  ``ImportError``, ``AttributeError``, ``PermissionError`` (capability denied);
* ``list_skills`` — детерминированный порядок;
* hot-reload — NotImplementedError (scaffold).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.core.ai.skill_registry import SkillRegistry, SkillSpec

# ─── Module-level handler'ы для invoke-тестов ───────────────────────────────


def _sync_handler(x: int, y: int = 0) -> int:
    """Sync handler для тестов invoke()."""
    return x + y


async def _async_handler(x: int) -> int:
    """Async handler для тестов invoke()."""
    return x * 2


def _echo_handler(**kwargs: Any) -> dict[str, Any]:
    """Echo handler для теста пробрасывания kwargs."""
    return dict(kwargs)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _register(
    registry: SkillRegistry,
    *,
    skill_id: str = "test.sync",
    handler: str = "tests.unit.core.ai.test_skill_registry:_sync_handler",
    capabilities: list[str] | None = None,
) -> SkillSpec:
    """Зарегистрировать skill напрямую в ``_skills`` (test-internal)."""
    spec = SkillSpec(
        id=skill_id, version="1.0.0", handler=handler, capabilities=capabilities or []
    )
    registry._skills[skill_id] = spec  # noqa: SLF001
    return spec


# ─── from_toml_manifest: edge-cases ─────────────────────────────────────────


def test_from_toml_manifest_with_no_skill_section(tmp_path: Path) -> None:
    """``skill = None`` в TOML → пустой список (line 157)."""
    registry = SkillRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        '[meta]\nname = "x"\n',  # нет [[skill]] секции вообще
        encoding="utf-8",
    )
    assert registry.from_toml_manifest(plugin_toml) == []
    assert registry.list_skills() == []


def test_from_toml_manifest_with_empty_array(tmp_path: Path) -> None:
    """``[[skill]] = []`` (пустой массив) → пустой список."""
    registry = SkillRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text("skill = []\n", encoding="utf-8")
    assert registry.from_toml_manifest(plugin_toml) == []


def test_from_toml_manifest_missing_required_version(tmp_path: Path) -> None:
    """Отсутствует required поле ``version`` → ValueError (line 176-177)."""
    registry = SkillRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        '[[skill]]\nid = "credit.score"\nhandler = "skills.credit:score"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc_info:
        registry.from_toml_manifest(plugin_toml)
    msg = str(exc_info.value)
    assert "skill[0]" in msg
    assert "version" in msg


def test_from_toml_manifest_missing_handler(tmp_path: Path) -> None:
    """Отсутствует handler → ValueError (тот же путь, другая field)."""
    registry = SkillRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text('[[skill]]\nid = "x"\nversion = "1.0"\n', encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        registry.from_toml_manifest(plugin_toml)
    assert "handler" in str(exc_info.value)


def test_from_toml_manifest_multiple_skills(tmp_path: Path) -> None:
    """Несколько ``[[skill]]`` секций — все регистрируются в ``_skills``."""
    registry = SkillRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        '[[skill]]\nid = "a.one"\nversion = "1.0"\nhandler = "m:a"\n\n'
        '[[skill]]\nid = "b.two"\nversion = "2.0"\nhandler = "m:b"\n',
        encoding="utf-8",
    )
    specs = registry.from_toml_manifest(plugin_toml)
    assert len(specs) == 2
    assert {s.id for s in specs} == {"a.one", "b.two"}


def test_from_toml_manifest_with_full_optional_fields(tmp_path: Path) -> None:
    """Полный набор опциональных полей корректно парсится."""
    registry = SkillRegistry()
    plugin_toml = tmp_path / "plugin.toml"
    plugin_toml.write_text(
        "[[skill]]\n"
        'id = "credit.score"\n'
        'version = "1.2.0"\n'
        'handler = "ext.credit:score"\n'
        'description = "Score calc"\n'
        'input_schema = "schemas/in.json"\n'
        'output_schema = "schemas/out.json"\n'
        'capabilities = ["db.read.orders"]\n'
        'policy_ref = "credit_strict"\n'
        'protocols = ["mcp", "openai_tools"]\n'
        "timeout_s = 12.5\n"
        "tenant_aware = true\n"
        'feature_flag = "CREDIT_V2"\n',
        encoding="utf-8",
    )
    [spec] = registry.from_toml_manifest(plugin_toml)
    assert spec.description == "Score calc"
    assert spec.input_schema == "schemas/in.json"
    assert spec.capabilities == ["db.read.orders"]
    assert spec.policy_ref == "credit_strict"
    assert spec.protocols == ["mcp", "openai_tools"]
    assert spec.timeout_s == 12.5
    assert spec.tenant_aware is True
    assert spec.feature_flag == "CREDIT_V2"


# ─── from_python_decorator: scaffold NotImplementedError ────────────────────


def test_from_python_decorator_raises_not_implemented() -> None:
    """Scaffold: ``from_python_decorator`` поднимает NotImplementedError (line 200-201)."""

    def my_func() -> int:
        return 42

    registry = SkillRegistry()
    with pytest.raises(NotImplementedError) as exc_info:
        registry.from_python_decorator(my_func)
    assert "S26 W5" in str(exc_info.value)


# ─── invoke: success paths (sync + async) ───────────────────────────────────


@pytest.mark.asyncio
async def test_invoke_sync_handler_returns_value() -> None:
    """invoke() вызывает sync-handler и возвращает результат (lines 231-291)."""
    registry = SkillRegistry()
    _register(registry)
    result = await registry.invoke("test.sync", x=2, y=3)
    assert result == 5


@pytest.mark.asyncio
async def test_invoke_async_handler_returns_value() -> None:
    """invoke() детектит ``iscoroutinefunction`` и await'ит async-handler."""
    registry = SkillRegistry()
    _register(
        registry,
        skill_id="test.async",
        handler="tests.unit.core.ai.test_skill_registry:_async_handler",
    )
    result = await registry.invoke("test.async", x=10)
    assert result == 20


@pytest.mark.asyncio
async def test_invoke_passes_kwargs_correctly() -> None:
    """**kwargs пробрасываются в handler без модификации."""
    registry = SkillRegistry()
    _register(
        registry,
        skill_id="test.echo",
        handler="tests.unit.core.ai.test_skill_registry:_echo_handler",
    )
    result = await registry.invoke("test.echo", a=1, b="two", c=[3])
    assert result == {"a": 1, "b": "two", "c": [3]}


# ─── invoke: error paths ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invoke_unknown_skill_raises_key_error() -> None:
    """invoke() на неизвестный skill_id → KeyError (line 226-228)."""
    registry = SkillRegistry()
    with pytest.raises(KeyError) as exc_info:
        await registry.invoke("does.not.exist")
    assert "does.not.exist" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invoke_handler_without_colon_raises_value_error() -> None:
    """Handler без ``:`` → ValueError (line 231-235)."""
    registry = SkillRegistry()
    _register(registry, skill_id="bad", handler="no_colon_here")
    with pytest.raises(ValueError) as exc_info:
        await registry.invoke("bad")
    assert "module:fn" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invoke_handler_module_not_found_raises_import_error() -> None:
    """Handler указывает на несуществующий модуль → ImportError (line 273-277)."""
    registry = SkillRegistry()
    _register(
        registry,
        skill_id="missing.mod",
        handler="definitely_does_not_exist_module_xyz:func",
    )
    with pytest.raises(ImportError) as exc_info:
        await registry.invoke("missing.mod")
    msg = str(exc_info.value)
    # Сообщение содержит module name (handler[:handler.index(":")]) и сам handler.
    assert "definitely_does_not_exist_module_xyz" in msg
    assert "definitely_does_not_exist_module_xyz:func" in msg


@pytest.mark.asyncio
async def test_invoke_handler_function_not_found_raises_attribute_error() -> None:
    """Module импортируется, но функции с таким именем нет → AttributeError (line 279-284)."""
    registry = SkillRegistry()
    _register(
        registry,
        skill_id="missing.fn",
        handler="tests.unit.core.ai.test_skill_registry:_definitely_missing_function_xyz",
    )
    with pytest.raises(AttributeError) as exc_info:
        await registry.invoke("missing.fn")
    assert "_definitely_missing_function_xyz" in str(exc_info.value)


@pytest.mark.asyncio
async def test_invoke_capability_denied_raises_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``_global_capability_check`` поднимает → PermissionError (line 260-268)."""
    from src.backend.core.plugin_runtime import sandbox as sandbox_module

    def fake_check(cap: str, _ctx: str, _tenant: object) -> None:
        raise RuntimeError(f"denied: {cap}")

    monkeypatch.setattr(
        sandbox_module, "_global_capability_check", fake_check, raising=False
    )

    registry = SkillRegistry()
    _register(registry, capabilities=["db.read.orders"])

    with pytest.raises(PermissionError) as exc_info:
        await registry.invoke("test.sync", x=1)
    msg = str(exc_info.value)
    assert "db.read.orders" in msg
    assert "test.sync" in msg


@pytest.mark.asyncio
async def test_invoke_capability_check_passes_when_no_denials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если checker установлен и НЕ поднимает → handler вызывается успешно."""
    from src.backend.core.plugin_runtime import sandbox as sandbox_module

    def always_allow(_cap: str, _ctx: str, _tenant: object) -> None:
        return None  # no-op

    monkeypatch.setattr(
        sandbox_module, "_global_capability_check", always_allow, raising=False
    )

    registry = SkillRegistry()
    _register(registry, capabilities=["any.cap"])
    result = await registry.invoke("test.sync", x=10, y=5)
    assert result == 15


@pytest.mark.asyncio
async def test_invoke_no_capability_check_runs_handler() -> None:
    """Без ``_global_capability_check`` в sandbox module — пропускаем (MVP)."""
    registry = SkillRegistry()
    _register(registry, capabilities=["any.cap"])
    result = await registry.invoke("test.sync", x=1, y=1)
    assert result == 2


# ─── list_skills: deterministic order ───────────────────────────────────────


def test_list_skills_returns_sorted_by_id() -> None:
    """list_skills() сортирует по ``id`` (line 343)."""
    registry = SkillRegistry()
    for sid in ("z.last", "a.first", "m.middle"):
        registry._skills[sid] = SkillSpec(  # noqa: SLF001
            id=sid, version="1.0", handler="m:fn"
        )
    skills = registry.list_skills()
    ids = [s.id for s in skills]
    assert ids == sorted(ids)
    assert ids == ["a.first", "m.middle", "z.last"]


def test_list_skills_empty_registry() -> None:
    """Пустой реестр → пустой список."""
    assert SkillRegistry().list_skills() == []


# ─── hot_reload: scaffold NotImplementedError ───────────────────────────────


@pytest.mark.asyncio
async def test_hot_reload_not_implemented() -> None:
    """hot_reload() — scaffold NotImplementedError до Wave B (line 293-302)."""
    registry = SkillRegistry()
    with pytest.raises(NotImplementedError):
        await registry.hot_reload()
