"""Юнит-тесты codegen Settings (W21.5a-e).

Покрывает:

* парсинг ``--field`` спецификаций (валидные / невалидные);
* рендер модуля Settings-класса для разных base;
* libcst-патчи ``__init__.py`` и ``settings.py`` (idempotent round-trip);
* round-trip CodegenSpec ↔ YAML;
* extract из существующего ast-класса.
"""

# ruff: noqa: S101

from __future__ import annotations

import ast
import textwrap

import libcst as cst
import pytest

from tools import codegen_settings as cg


class TestFieldSpecParsing:
    """Парсинг строковых ``--field`` спецификаций."""

    def test_minimal_non_secret(self) -> None:
        f = cg._parse_field("host:str:localhost:non-secret")
        assert f == cg.FieldSpec(
            name="host", type_="str", default="localhost", visibility="non-secret"
        )

    def test_secret_field(self) -> None:
        f = cg._parse_field("password:str::secret")
        assert f.is_secret
        assert f.python_default_literal == "..."
        assert f.default == ""

    def test_default_with_colons(self) -> None:
        """default может содержать двоеточия (URL host:port)."""
        f = cg._parse_field('bootstrap:str:"localhost:9092":non-secret')
        assert f.default == "localhost:9092"

    def test_constraints_parsed(self) -> None:
        f = cg._parse_field("port:int:8080:non-secret:ge=1,le=65535")
        assert f.constraints == ("ge=1", "le=65535")

    def test_optional_int_default_none(self) -> None:
        f = cg._parse_field("retry:int|None::non-secret")
        assert f.python_default_literal == "None"
        assert f.yaml_default_literal == "null"

    def test_bool_default(self) -> None:
        f = cg._parse_field("enabled:bool:True:non-secret")
        assert f.python_default_literal == "True"
        assert f.yaml_default_literal == "true"

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError):
            cg._parse_field("broken-spec")

    def test_invalid_visibility_raises(self) -> None:
        with pytest.raises(ValueError):
            cg._parse_field("name:str:val:wrong")


class TestRenderClassModule:
    """Генерация Python-модуля Settings-класса."""

    def test_default_base(self) -> None:
        out = cg._render_class_module(
            "demo", "DEMO_", [cg._parse_field("host:str:localhost:non-secret")]
        )
        assert "class DemoSettings(BaseSettingsWithLoader):" in out
        assert 'env_prefix="DEMO_"' in out
        assert "demo_settings = DemoSettings()" in out
        ast.parse(out)  # синтаксически валиден

    def test_connector_base(self) -> None:
        out = cg._render_class_module(
            "kafka",
            "KAFKA_",
            [cg._parse_field("topic:str:t1:non-secret")],
            base="BaseConnectorSettings",
        )
        assert (
            "from src.core.config.integration_base import BaseConnectorSettings" in out
        )
        assert "class KafkaSettings(BaseConnectorSettings):" in out
        ast.parse(out)

    def test_unknown_base_raises(self) -> None:
        with pytest.raises(ValueError):
            cg._render_class_module(
                "x", "X_", [cg._parse_field("a:str:b:non-secret")], base="NoSuch"
            )


class TestLibcstPatches:
    """libcst-патчи ``__init__.py`` и ``settings.py``."""

    def test_add_import_to_existing_block(self) -> None:
        src = textwrap.dedent(
            """
            from foo.bar import (
                A,
                B,
            )
            """
        ).lstrip()
        module = cst.parse_module(src)
        new_module, changed = cg._add_to_import_from(module, "foo.bar", ["C", "D"])
        assert changed
        # Все 4 имени присутствуют, исходные первыми, новые в конце.
        assert "A" in new_module.code
        assert "B" in new_module.code
        assert "C" in new_module.code
        assert "D" in new_module.code
        # Идемпотентность: повторный вызов с теми же именами — без изменений.
        again, again_changed = cg._add_to_import_from(new_module, "foo.bar", ["A", "B"])
        assert not again_changed

    def test_add_import_creates_new_when_missing(self) -> None:
        src = "from foo.bar import A\n"
        module = cst.parse_module(src)
        new_module, changed = cg._add_to_import_from(module, "baz.qux", ["X"])
        assert changed
        assert "from baz.qux import X" in new_module.code
        # Но и старый импорт остался.
        assert "from foo.bar import A" in new_module.code

    def test_extend_all_tuple_preserves_order(self) -> None:
        src = textwrap.dedent(
            """
            __all__ = (
                "A",
                "B",
            )
            """
        ).lstrip()
        module = cst.parse_module(src)
        new_module, changed = cg._extend_all_tuple(module, ["X", "Y"])
        assert changed
        code = new_module.code
        # Исходный порядок сохранён, новые в конце.
        idx_a, idx_b, idx_x, idx_y = (
            code.index('"A"'),
            code.index('"B"'),
            code.index('"X"'),
            code.index('"Y"'),
        )
        assert idx_a < idx_b < idx_x < idx_y

    def test_extend_all_tuple_idempotent(self) -> None:
        src = '__all__ = ("A", "B")\n'
        module = cst.parse_module(src)
        new_module, changed = cg._extend_all_tuple(module, ["A", "B"])
        assert not changed

    def test_add_class_attribute(self) -> None:
        src = textwrap.dedent(
            """
            class Settings:
                foo: int = 1
            """
        ).lstrip()
        module = cst.parse_module(src)
        new_module, changed = cg._add_class_attribute(
            module, "Settings", "bar", "str", '"hello"'
        )
        assert changed
        assert 'bar: str = "hello"' in new_module.code
        # Идемпотентность.
        again, again_changed = cg._add_class_attribute(
            new_module, "Settings", "bar", "str", '"hello"'
        )
        assert not again_changed


class TestSpecYamlRoundTrip:
    """``CodegenSpec`` ↔ YAML: загрузка и сохранение сохраняют данные."""

    def test_round_trip(self, tmp_path) -> None:
        spec = cg.CodegenSpec(
            name="kafka",
            env_prefix="KAFKA_",
            base="BaseConnectorSettings",
            fields=[
                cg.FieldSpec(
                    name="bootstrap",
                    type_="str",
                    default="localhost:9092",
                    visibility="non-secret",
                    constraints=("min_length=1",),
                ),
                cg.FieldSpec(
                    name="username", type_="str", default="", visibility="secret"
                ),
            ],
        )
        path = tmp_path / "kafka.yml"
        cg._spec_to_yaml(spec, path)

        loaded = cg._spec_from_yaml(path)
        assert loaded.name == spec.name
        assert loaded.env_prefix == spec.env_prefix
        assert loaded.base == spec.base
        assert len(loaded.fields) == len(spec.fields)
        for orig, back in zip(spec.fields, loaded.fields):
            assert orig.name == back.name
            assert orig.type_ == back.type_
            assert orig.default == back.default
            assert orig.visibility == back.visibility
            assert tuple(orig.constraints) == tuple(back.constraints)

    def test_invalid_spec_raises(self, tmp_path) -> None:
        path = tmp_path / "bad.yml"
        path.write_text(
            "name: BadName  # uppercase нельзя\nenv_prefix: bad_\nfields: []\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            cg._spec_from_yaml(path)


class TestExtractSpec:
    """Reverse-codegen: построение ``CodegenSpec`` из AST класса."""

    def test_extract_from_ast(self, tmp_path, monkeypatch) -> None:
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        (services_dir / "kafka.py").write_text(
            textwrap.dedent(
                """
                from typing import ClassVar
                from pydantic import Field
                from pydantic_settings import SettingsConfigDict
                from src.core.config.integration_base import BaseConnectorSettings


                class KafkaSettings(BaseConnectorSettings):
                    yaml_group: ClassVar[str] = "kafka"
                    model_config = SettingsConfigDict(env_prefix="KAFKA_", extra="forbid")

                    bootstrap: str = Field("localhost:9092", description="x")
                    timeout: int = Field(30, ge=1, le=300, description="y")
                    username: str = Field(..., description="z")
                """
            ).lstrip(),
            encoding="utf-8",
        )
        monkeypatch.setattr(cg, "SERVICES_DIR", services_dir)
        spec = cg.extract_spec_from_class("KafkaSettings")
        assert spec.name == "kafka"
        assert spec.env_prefix == "KAFKA_"
        assert spec.base == "BaseConnectorSettings"
        assert {f.name for f in spec.fields} == {"bootstrap", "timeout", "username"}
        username = next(f for f in spec.fields if f.name == "username")
        assert username.is_secret
        timeout = next(f for f in spec.fields if f.name == "timeout")
        assert timeout.constraints == ("ge=1", "le=300")

    def test_extract_unknown_class_raises(self, tmp_path, monkeypatch) -> None:
        services_dir = tmp_path / "services"
        services_dir.mkdir()
        monkeypatch.setattr(cg, "SERVICES_DIR", services_dir)
        with pytest.raises(LookupError):
            cg.extract_spec_from_class("DoesNotExist")
