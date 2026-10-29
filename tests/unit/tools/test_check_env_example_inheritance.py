"""A1 (ADR-0385): ``check_env_example`` обязан учитывать наследование полей.

Дефект
------
Сканер env-переменных смотрел только ``node.body`` самого класса
Settings. Поля, объявленные в mixin'ах/базовых классах
(``ConnectionMixin``, ``BaseBotChannelSettings``), терялись — поэтому
реально живые секреты помечались как «не используются в Settings» и не
видились гейту ADR-0373.

Ожидание
---------
* креды, унаследованные от ``ConnectionMixin``
  (``AI_USERNAME``/``AI_PASSWORD``/``AI_API_KEY``,
  ``MINIMAX_USERNAME``/``MINIMAX_PASSWORD``), видны гейту;
* креды, унаследованные от ``BaseBotChannelSettings``
  (``EXPRESS_SECRET_KEY``/``EXPRESS_SIGNATURE_SECRET``,
  ``TELEGRAM_SECRET_KEY``/``TELEGRAM_SIGNATURE_SECRET``), видны гейту;
* все девять ключей описаны в ``.env.example`` пустыми значениями
  (правило ADR-0373 «в .env только секреты»).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

_TOOLS_PATH = Path(__file__).resolve().parents[3] / "tools" / "check_env_example.py"
_spec = importlib.util.spec_from_file_location(
    "tools.check_env_example_inheritance", _TOOLS_PATH
)
module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(module)

collect_env_fields = module.collect_env_fields
collect_expected_env_vars = module.collect_expected_env_vars
collect_env_example_vars = module.collect_env_example_vars
parse_env_example = module.parse_env_example
ENV_EXAMPLE = module.ENV_EXAMPLE
CONFIG_DIR = module.CONFIG_DIR

runner = CliRunner()

INHERITED_SECRET_VARS: tuple[str, ...] = (
    "AI_API_KEY",
    "AI_PASSWORD",
    "AI_USERNAME",
    "MINIMAX_USERNAME",
    "MINIMAX_PASSWORD",
    "EXPRESS_SECRET_KEY",
    "EXPRESS_SIGNATURE_SECRET",
    "TELEGRAM_SECRET_KEY",
    "TELEGRAM_SIGNATURE_SECRET",
)


class TestInheritedFieldsAreCollected:
    """Наследованные через mixin/base поля обязаны попадать в env-карту."""

    @pytest.mark.parametrize("env_var", INHERITED_SECRET_VARS)
    def test_inherited_secret_is_known_setting(self, env_var: str) -> None:
        """Унаследованный секрет известен гейту как переменная Settings."""
        fields = collect_env_fields(CONFIG_DIR)
        assert env_var in fields, (
            f"{env_var} не найден среди env-переменных Settings — "
            "наследование полей не разрешается"
        )

    def test_own_fields_still_collected(self) -> None:
        """Собственные поля класса не теряются после перехода на резолвер."""
        fields = collect_env_fields(CONFIG_DIR)
        assert "AI_DEFAULT_PROVIDER" in fields
        assert "EXPRESS_BOTX_URL" in fields

    def test_expected_env_vars_contains_inherited(self) -> None:
        """Публичный API сбора ожидаемых переменных учитывает наследование."""
        expected = collect_expected_env_vars(CONFIG_DIR)
        for env_var in INHERITED_SECRET_VARS:
            assert env_var in expected


class TestEnvExampleDocumentsInheritedSecrets:
    """Девять живых секретов описаны в ``.env.example`` пустыми значениями."""

    @pytest.mark.parametrize("env_var", INHERITED_SECRET_VARS)
    def test_documented_with_empty_value(self, env_var: str) -> None:
        """Ключ есть в шаблоне и его значение пустое (ADR-0373)."""
        documented = dict(parse_env_example(ENV_EXAMPLE))
        assert env_var in documented, f"{env_var} отсутствует в .env.example"
        assert documented[env_var] == "", (
            f"{env_var} должен иметь пустое значение в шаблоне"
        )

    def test_documented_and_expected_sets_match_for_inherited(self) -> None:
        """Девять ключей не должны попадать в «лишние» переменные."""
        expected = collect_expected_env_vars(CONFIG_DIR)
        documented = collect_env_example_vars(ENV_EXAMPLE)
        extra = documented - expected
        for env_var in INHERITED_SECRET_VARS:
            assert env_var not in extra, (
                f"{env_var} ошибочно помечен как «не используется в Settings»"
            )


class TestCliReportsNoInheritedSecretsAsUnused:
    """CLI-гейт не должен рапортовать унаследованные секреты как лишние."""

    def test_cli_output_has_no_inherited_secrets_in_extra(self) -> None:
        """В human-readable отчёте нет девяти ключей в списке лишних."""
        result = runner.invoke(module.app, [])
        output = result.stdout + (result.stderr or "")
        extra_block = output.split("не используются в Settings:")[-1]
        for env_var in INHERITED_SECRET_VARS:
            assert env_var not in extra_block, (
                f"{env_var} попал в список неиспользуемых переменных"
            )

    def test_json_payload_extra_list_excludes_inherited(self) -> None:
        """В JSON-отчёте девяти ключей нет в ``extra``."""
        result = runner.invoke(module.app, ["--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        for env_var in INHERITED_SECRET_VARS:
            assert env_var not in payload["extra"]
