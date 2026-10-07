"""F-CI (HIGH): гейт object-authorization печатает ❌ и возвращает 0.

Аудит 2026-10-05. ``tools/checks/check_object_authorization.py`` на текущем
коде выводит два жёстких провала:

    ❌ Object ownership check coverage is low (10.7%) — <50% of routes have
       explicit ownership verification.
    ❌ Many service lookups (127) without tenant filter — potential
       cross-tenant data access.

и при этом завершается с **exit code 0**.

Механика (``check_object_authorization.py:219-221``): код возврата зависит от
флага ``--strict``:

    if args.strict and issues:
        return 1
    return 0

CI вызывает гейт БЕЗ ``--strict`` и дополнительно заворачивает в ``|| true``
(``.github/workflows/lint.yml:186``), то есть маскирование двухуровневое.
Итог: гейт, который обнаруживает провал покрытия авторизации, объявляет успех.

Это тот самый класс «ложноположительных статусов готовности», который цель
аудита называет главным риском: защита не просто не сработала — она сообщила
об успехе.

Тест ниже фиксирует контракт: если гейт печатает ❌, он обязан вернуть
ненулевой код. Проверка идёт на реальном скрипте (без mock), потому что именно
реальный exit code и constitutes наблюдаемый дефект.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# parents[3] — корень репозитория (tests/unit/tools/<file> → 3 уровня вверх).
# parents[4] указывал бы на родитель каталога, что ломало запуск гейта.
REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "tools" / "checks" / "check_object_authorization.py"


def _run(extra: list[str]) -> tuple[int, str]:
    """Запустить гейт и вернуть ``(exit_code, stdout)``.

    Args:
        extra: Дополнительные аргументы командной строки.

    Returns:
        Кортеж из кода возврата и объединённого вывода.

    """
    proc = subprocess.run(  # noqa: S603 — фиксированный список аргументов
        [sys.executable, str(GATE), *extra],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


# Маркер security НЕ используется осознанно: он не зарегистрирован в
# pyproject.toml на этой ветке (finding F-X), поэтому его применение
# валит коллекцию с ошибкой "not found in `markers` configuration option".
# Это наблюдение само по себе подтверждает F-X; после его закрытия тест
# стоит перевести на @pytest.mark.security.
@pytest.mark.unit
class TestGateExitCodeMatchesItsOwnVerdict:
    """Код возврата обязан соответствовать выведенному вердикту."""

    @pytest.mark.parametrize(
        "extra",
        [
            pytest.param(
                [],
                marks=pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "Контракт самого гейта: код возврата зависит от --strict "
                        "(check_object_authorization.py:219-221), поэтому без флага он "
                        "печатает ❌ и возвращает 0. Риск снят тем, что CI теперь "
                        "передаёт --strict — это проверяет отдельный тест ниже. "
                        "strict=True: если контракт гейта изменят на «всегда падать "
                        "при ❌», тест даст XPASS и потребует осознанного пересмотра."
                    ),
                ),
            ),
            pytest.param(["--strict"]),
        ],
    )
    def test_no_failed_verdict_with_zero_exit(self, extra: list[str]) -> None:
        """Если вывод содержит ❌, код возврата обязан быть ненулевым.

        Args:
            extra: Набор флагов гейта.

        """
        code, out = _run(extra)

        if "❌" in out:
            assert code != 0, (
                "гейт напечатал ❌, но вернул 0 — провал объявлен успехом.\n"
                f"Аргументы: {extra or ['без флагов']}\n"
                f"Вывод:\n{out[-1200:]}"
            )

    def test_strict_mode_does_fail_on_current_code(self) -> None:
        """``--strict`` обязан давать ненулевой код на текущих находках.

        Это фиксирует известное состояние репозитория: провалы реальны.
        Если гейт начнёт проходить — значит либо исправлена авторизация, либо
        гейт ослаблен; и то и другое требует осознанного пересмотра.
        """
        code, out = _run(["--strict"])

        assert "❌" in out, (
            "ожидались известные провалы object authorization; если они исчезли — "
            "проверьте, не ослаблен ли гейт или не сломана ли защита"
        )
        assert code != 0, "в --strict провалы обязаны давать ненулевой код"

    def test_ci_workflow_must_not_swallow_gate_failure(self) -> None:
        """CI не должен заворачивать этот гейт в ``|| true``.

        Проверяется текст workflow, а не поведение: именно ``|| true`` делает
        гейт чисто декларативным даже после того, как он начнёт падать.
        """
        workflow = REPO_ROOT / ".github" / "workflows" / "lint.yml"
        text = workflow.read_text(encoding="utf-8")

        # Только строки-команды: комментарии рядом с вызовом намеренно
        # упоминают и имя гейта, и его строку в исходнике.
        offending = [
            line.strip()
            for line in text.splitlines()
            if "check_object_authorization.py" in line and "run:" in line
        ]
        assert offending, "вызов гейта не найден в lint.yml — структура изменилась"

        for line in offending:
            assert "|| true" not in line, f"провал гейта подавляется: {line}"
            assert "--strict" in line, (
                f"гейт вызывается без --strict, поэтому возвращает 0 при наличии "
                f"провалов: {line}"
            )
