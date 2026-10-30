"""ADR-0403: явный allowlist для класса ``missing-secret`` в config_audit.

Дефект
------
``tools/config_audit.py`` умел блокировать гейт по классу
``missing-secret`` (ADR-0373: секрет не документирован в ``.env.example``),
но долг по этому классу нигде не был зафиксирован явно: allowlist
``tools/config_audit_allowlist.txt`` — общий для всех видов расхождений и
без обязательных обоснований. Решение «переменная сознательно не
документирована» нельзя было выразить отдельным, проверяемым артефактом.

Ожидание
--------
* ``.security/config-audit-missing-secret-allowlist.txt`` — отдельный
  allowlist класса ``missing-secret``; каждая запись обязана содержать
  ``owner=`` и ``reason=``;
* запись без ``owner``/``reason`` **не** считается allowlisted — гейт
  продолжает блокировать (сигнал не теряется);
* гейт по классу ``missing-secret`` на текущем состоянии репозитория = 0
  расхождений (exit 0).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOL = REPO_ROOT / "tools" / "config_audit.py"
ALLOWLIST = REPO_ROOT / ".security" / "config-audit-missing-secret-allowlist.txt"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _run_audit(
    *,
    env_example: Path,
    allowlist: Path,
    missing_secret_allowlist: Path | None = None,
    profiles_dir: Path | None = None,
    scope: str = "missing",
) -> subprocess.CompletedProcess[str]:
    """Запустить ``tools/config_audit.py`` с подменёнными входами.

    Args:
        env_example: Файл-шаблон окружения.
        allowlist: Общий allowlist (baseline всех видов расхождений).
        missing_secret_allowlist: Явный allowlist класса missing-secret.
        profiles_dir: Каталог профилей (по умолчанию — репозиторный).
        scope: Scope гейта.

    Returns:
        Результат запуска CLI.

    """
    cmd = [
        sys.executable,
        str(TOOL),
        "--scope",
        scope,
        "--json",
        "--env-example",
        str(env_example),
        "--allowlist",
        str(allowlist),
    ]
    if missing_secret_allowlist is not None:
        cmd += ["--missing-secret-allowlist", str(missing_secret_allowlist)]
    if profiles_dir is not None:
        cmd += ["--profiles-dir", str(profiles_dir)]
    return subprocess.run(  # noqa: S603 — фиксированный cmd, без shell
        cmd, capture_output=True, text=True, cwd=REPO_ROOT, check=False
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    """Разобрать JSON-вывод аудита.

    Args:
        result: Результат запуска CLI.

    Returns:
        Разобранный payload.

    """
    return json.loads(result.stdout)


def test_missing_secret_allowlist_file_exists() -> None:
    """Явный allowlist класса missing-secret существует в репозитории."""
    assert ALLOWLIST.is_file(), f"нет файла {ALLOWLIST}"
    text = ALLOWLIST.read_text(encoding="utf-8")
    assert "owner=" in text, "в allowlist нет ни одной записи с owner="


def test_allowlist_entries_require_owner_and_reason() -> None:
    """Каждая запись allowlist обязана иметь owner= и reason=."""
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert "owner=" in stripped, f"запись без owner=: {stripped}"
        assert "reason=" in stripped, f"запись без reason=: {stripped}"


def test_gate_for_missing_secret_class_is_zero() -> None:
    """Гейт по классу missing-secret на текущем состоянии = 0 (exit 0)."""
    result = _run_audit(env_example=ENV_EXAMPLE, allowlist=ALLOWLIST)

    assert result.returncode == 0, (
        f"config_audit --scope missing: exit {result.returncode}\n{result.stdout}"
    )
    payload = _payload(result)
    assert payload["blocking_findings"] == 0
    assert payload["new_violations"] == []


def test_undocumented_secret_blocks_the_gate(tmp_path: Path) -> None:
    """Секрет, не документированный в .env.example, блокирует гейт."""
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        ENV_EXAMPLE.read_text(encoding="utf-8").replace("SEC_SECRET_KEY=", ""),
        encoding="utf-8",
    )
    allowlist = tmp_path / "allowlist.txt"
    allowlist.write_text("", encoding="utf-8")

    result = _run_audit(env_example=env_example, allowlist=allowlist)

    assert result.returncode == 1, "недокументированный секрет должен блокировать"
    payload = _payload(result)
    assert payload["new_violations"], "ожидались новые нарушения missing-secret"


def test_allowlisted_entry_with_owner_and_reason_does_not_block(tmp_path: Path) -> None:
    """Запись с owner= и reason= снимает блокировку (осознанный долг)."""
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        ENV_EXAMPLE.read_text(encoding="utf-8").replace("SEC_SECRET_KEY=", ""),
        encoding="utf-8",
    )
    allowlist = tmp_path / "allowlist.txt"
    allowlist.write_text("", encoding="utf-8")
    secret_allowlist = tmp_path / "missing-secret-allowlist.txt"
    secret_allowlist.write_text(
        "".join(
            f"missing-secret:{profile}:security:SEC_SECRET_KEY  # owner=security | "
            "reason=секрет выдаётся Vault'ом\n"
            for profile in ("dev", "dev_light", "staging", "prod")
        ),
        encoding="utf-8",
    )

    result = _run_audit(
        env_example=env_example,
        allowlist=allowlist,
        missing_secret_allowlist=secret_allowlist,
    )

    payload = _payload(result)
    assert payload["new_violations"] == []
    assert result.returncode == 0


def test_entry_without_owner_does_not_suppress_violation(tmp_path: Path) -> None:
    """Запись без owner= не считается allowlisted — сигнал не теряется."""
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        ENV_EXAMPLE.read_text(encoding="utf-8").replace("SEC_SECRET_KEY=", ""),
        encoding="utf-8",
    )
    allowlist = tmp_path / "allowlist.txt"
    allowlist.write_text("", encoding="utf-8")
    secret_allowlist = tmp_path / "missing-secret-allowlist.txt"
    secret_allowlist.write_text(
        "".join(
            f"missing-secret:{profile}:security:SEC_SECRET_KEY  # reason=без owner\n"
            for profile in ("dev", "dev_light", "staging", "prod")
        ),
        encoding="utf-8",
    )

    result = _run_audit(
        env_example=env_example,
        allowlist=allowlist,
        missing_secret_allowlist=secret_allowlist,
    )

    assert result.returncode == 1, "запись без owner= не должна снимать блокировку"
    payload = _payload(result)
    assert payload["new_violations"], "ожидались новые нарушения missing-secret"
    assert payload["unjustified_allowlist_entries"], (
        "записи без owner= должны быть отмечены как необоснованные"
    )
