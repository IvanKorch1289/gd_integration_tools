"""Регрессионные тесты для pre-prod гейта #21 ConfigValidator (S17 K-ARCH-1).

Гейт молча деградировал: он искал файл
``src/backend/core/config/validator.py``, который перестал существовать после
перевода модуля в пакет ``config/validator/``. Проверка всегда уходила в ветку
WARN «module not found» и не запускала валидатор вообще, хотя объявляла
CRITICAL-правило ``waf.strict_required_in_prod``.

Два независимых класса дефекта закрываются здесь:

1. **Мёртвая проверка** — валидатор обязан реально импортироваться и
   выполняться, а не проверять существование устаревшего пути.
2. **Холостая проверка** — сравнение severity регистрозависимое. Значения
   ``ConfigSeverity`` — ``'critical'``/``'warning'``/``'info'`` в нижнем
   регистре, поэтому сравнение с ``'CRITICAL'`` всегда даёт пустой список и
   гейт остаётся зелёным при настоящих CRITICAL-нарушениях.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "checks"))

import pre_prod_check  # noqa: E402


class TestConfigValidatorGateIsNotDead:
    """Валидатор существует и гейт его запускает."""

    def test_validator_lives_in_a_package_not_a_module_file(self) -> None:
        """Путь, который проверял гейт, не существует; класс живёт в пакете.

        Это и есть причина деградации: рефакторинг ``validator.py`` →
        ``validator/`` не поправил гейт.
        """
        repo_root = pre_prod_check.ROOT
        assert not (repo_root / "src/backend/core/config/validator.py").exists()
        assert (repo_root / "src/backend/core/config/validator/__init__.py").exists(), (
            "ConfigValidator должен жить в пакете validator/"
        )

    def test_check_runs_and_passes_on_current_config(self) -> None:
        """На текущей конфигурации гейт проходит и не остаётся WARN-заглушкой."""
        result = pre_prod_check._check_config_validator()
        assert result.name == "config-validator"
        assert result.ok is True, result.error_msg
        # Раньше здесь всегда был skip_reason про «module not found».
        assert not getattr(result, "skip_reason", None)


class TestConfigValidatorGateIsNotVacuous:
    """Гейт обязан падать при настоящем CRITICAL-нарушении."""

    @staticmethod
    def _run(snippet: str) -> tuple[int, str]:
        """Выполнить сниппет в том же окружении, что и гейт."""
        import subprocess

        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            cwd=str(pre_prod_check.ROOT),
            check=False,
        )
        return proc.returncode, proc.stdout

    def test_severity_comparison_must_be_case_insensitive(self) -> None:
        """Значения ConfigSeverity в нижнем регистре.

        Проверяется именно код самого гейта: сниппет собирается строкой внутри
        ``_check_config_validator``, поэтому сравнение с ``'CRITICAL'``
        (без ``.lower()``) тихо ломало гейт — он всегда находил пустой список
        CRITICAL и оставался зелёным. Тест ловит именно эту регрессию в коде
        гейта, а не в собственной копии логики.
        """
        import inspect

        from src.backend.core.config.validator._helpers import ConfigSeverity

        assert str(ConfigSeverity.CRITICAL) == "critical"
        assert "critical".endswith("CRITICAL") is False

        gate_source = inspect.getsource(pre_prod_check._check_config_validator)
        assert ".lower() == 'critical'" in gate_source, (
            "Гейт обязан сравнивать severity регистронезависимо: значения "
            "ConfigSeverity в нижнем регистре, и сравнение с 'CRITICAL' всегда "
            "даёт пустой список, т.е. гейт проходит при CRITICAL-нарушениях"
        )

    def test_gate_fails_on_critical_violation(self) -> None:
        """production + permissive WAF → CRITICAL → exit 1."""
        snippet = (
            "import sys; sys.path.insert(0, '.');"
            "from src.backend.core.config.validator import validate_startup_config;"
            "from src.backend.core.config.waf import WafSettings;"
            "from src.backend.core.config.settings import settings;"
            "s = settings.model_copy(update={'app': settings.app.model_copy("
            "update={'environment': 'production'})});"
            "v = validate_startup_config(s, WafSettings(strict=False),"
            " raise_on_critical_in_prod=False);"
            "crit = [x.code for x in v if str(x.severity).lower() == 'critical'];"
            "print('CRITICAL:', crit);"
            "sys.exit(1 if crit else 0)"
        )
        rc, out = self._run(snippet)
        assert rc == 1, f"ожидался exit 1 при CRITICAL, получено {rc}: {out}"
        assert "waf.strict_required_in_prod" in out, out

    def test_gate_passes_on_correct_prod_config(self) -> None:
        """Корректный prod-конфиг → CRITICAL нет → exit 0.

        В production CRITICAL получают сразу несколько правил: ``debug_mode``,
        ``enable_swagger`` и ``enable_redoc`` включены в dev-конфигурации.
        Здесь выключаются все три, чтобы проверить именно то правило, ради
        которого гейт чинился (WAF), без посторонних настроек.
        """
        snippet = (
            "import sys; sys.path.insert(0, '.');"
            "from src.backend.core.config.validator import validate_startup_config;"
            "from src.backend.core.config.waf import WafSettings;"
            "from src.backend.core.config.settings import settings;"
            "app = settings.app.model_copy(update={'environment': 'production',"
            " 'debug_mode': False, 'enable_swagger': False,"
            " 'enable_redoc': False});"
            "s = settings.model_copy(update={'app': app});"
            "v = validate_startup_config(s, WafSettings("
            "strict=True, allow_hosts=('esbgreendata',)),"
            " raise_on_critical_in_prod=False);"
            "crit = [x.code for x in v if str(x.severity).lower() == 'critical'];"
            "print('CRITICAL:', crit);"
            "sys.exit(1 if crit else 0)"
        )
        rc, out = self._run(snippet)
        assert rc == 0, f"корректный prod-конфиг должен проходить: {out}"
