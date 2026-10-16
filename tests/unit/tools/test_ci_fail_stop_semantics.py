"""Регрессия: CI-гейты не имеют права прятать ненулевой exit code.

Найдено аудитом 2026-10-09 (DEPENDENCIES-P0-002 / TYPE-P0-001). Два
подтверждённых случая:

1. ``make type-check-strict`` / ``make type-check-strict-profile``
   (make/quality.mk, оба вызываются из ``make ci``) глотали exit code
   mypy::

       mypy ... -p src || ( \\
           RET=$$?; \\
           if [ $$RET -eq 2 ]; then \\
               $(WARN) "... Bypassing..."; exit 0;   # <-- P0
           else \\
               exit $$RET; \\
           fi )

   mypy возвращает 2 при internal error / crash. То есть при падении mypy
   `make ci` рапортовал «Strict type check passed!» — при том что ни одной
   проверки типов выполнено не было.

2. ``pip-audit`` в make/security.mk подавлялся через ``|| true``, а
   компенсирующий гейт ``tools/pip_audit_gate.py`` был подключён только в
   ``.github/workflows/security.yml`` — но **не** в ``make ci``.
   Итог: make-гейт не знал про CVE зависимостей вообще.

Тесты проверяют определения целей, а не запускают пайплайн (`make ci`
занимает минуты). Поведенческий тест исполняет рецепт ровно так, как это
делает make: каждая логическая строка (после склейки `\\`-продолжений) —
отдельный вызов шелла, остановка на первой непустой.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
QUALITY_MK = REPO_ROOT / "make" / "quality.mk"
PIPELINES_MK = REPO_ROOT / "make" / "pipelines.mk"
SECURITY_MK = REPO_ROOT / "make" / "security.mk"


def _target_recipe(path: Path, target: str) -> str:
    """Тело рецепта make-цели (до следующей цели верхнего уровня)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{target}:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith(("##", "#")):
            break
        body.append(line)
    return "\n".join(body)


def _expand(recipe: str) -> str:
    """Раскрывает переменные, важные для анализа шелла."""
    return (
        recipe.replace("$(UV_RUN)", "uv run")
        .replace("$$?", "$?")
        .replace("$$RET", "$RET")
    )


def _drop_comments(recipe: str) -> str:
    """Убирает строки-комментарии (`# ...`).

    Иначе упоминание `tools/pip_audit_gate.py` в комментарии make/security.mk
    («гейт — tools/pip_audit_gate.py») выглядело бы как реальный вызов.
    """
    kept = []
    for line in recipe.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("##"):
            continue
        # make-комментарий в рецепте начинается с таба + '#'
        if re.match(r"^\s*#", line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _strip_messages(recipe: str) -> str:
    """Заменяет `$(INFO/WARN/ERROR/SUCCESS) "..."` на `true`.

    Важно: съедается ТОЛЬКО строка в кавычках, а не остаток строки.
    В `type-check-strict-profile` конструкция `$(WARN) "..."; exit 0; \\`
    стоит на одной строке — жадный `[^\\n]*` скрыл бы сам `exit 0`.
    """
    return re.sub(r'\$\((?:INFO|WARN|ERROR|SUCCESS)\)\s*"[^"]*"', "true", recipe)


def _logical_commands(recipe: str) -> list[str]:
    """Склеивает `\\`-продолжения и снимает make-префикс `@`/табуляцию.

    Без склейки многострочная конструкция `cmd || ( ... )` распалась бы на
    отдельные строки, и тест проверял бы syntax error вместо семантики гейта.
    """
    joined: list[str] = []
    buf = ""
    for raw in recipe.splitlines():
        line = raw.lstrip("\t")
        if not line.strip():
            continue
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        buf += line
        joined.append(buf)
        buf = ""
    if buf:
        joined.append(buf)

    out = []
    for line in joined:
        line = line.strip()
        if line.startswith("@"):
            line = line[1:].strip()
        if line:
            out.append(line)
    return out


def _make_like_status(commands: list[str], env: dict[str, str]) -> int:
    """Имитирует семантику make: отдельный шелл на строку, стоп на первой непустой.

    Возвращает код завершения последней выполненной строки
    (0 = ни одна строка не упала).
    """
    status = 0
    for cmd in commands:
        proc = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", **env},
        )
        if proc.returncode != 0:
            return proc.returncode
    return status


# ──────────────────────────── P0-05: mypy crash → exit 0 ────────────────────


@pytest.mark.parametrize(
    ("target",), [("type-check-strict",), ("type-check-strict-profile",)]
)
def test_type_check_gate_does_not_swallow_mypy_internal_error(target: str) -> None:
    """Гейты типов обязаны пробрасывать exit 2 (internal error) mypy.

    Раньше: `if [ $$RET -eq 2 ]; then ...; exit 0; fi` — краш mypy
    превращался в успех, и `make ci` рапортовал «Strict type check passed!»
    без единой выполненной проверки.
    """
    recipe = _strip_messages(
        _drop_comments(_expand(_target_recipe(QUALITY_MK, target)))
    )

    assert "exit 0" not in recipe, (
        f"`make {target}` содержит оператор `exit 0` в ветке обработки кода mypy: "
        "internal error / crash mypy приводит к «успешному» CI. "
        "Ненулевой код должен пробрасываться (make ci fail-stop)."
    )


def test_ci_type_stage_is_fail_stop_for_every_nonzero_mypy_code() -> None:
    """Поведенческая проверка рецепта `type-check-strict`.

    Обязан вернуть ненулевой код для ЛЮБОГО ненулевого exit mypy:
    1 = ошибки типов, 2 = internal error, 124 = timeout.
    """
    recipe = _expand(_target_recipe(QUALITY_MK, "type-check-strict"))
    recipe = _strip_messages(_drop_comments(recipe))
    recipe = re.sub(
        r"MYPY_USE_MYPYC=0 uv run python -X faulthandler -m mypy"
        r"[\\\s]+--cache-dir=\S+"
        r"[\\\s]+(?:-p src|.*?-p src)",
        "sh -c 'exit $MYPY_RC'",
        recipe,
        flags=re.DOTALL,
    )
    recipe = _drop_comments(recipe)

    if "sh -c" not in recipe:
        pytest.skip("рецепт изменился — обновите подстановку стаба")

    commands = _logical_commands(recipe)

    for mypy_rc in (1, 2, 124):
        status = _make_like_status(commands, {"MYPY_RC": str(mypy_rc)})
        assert status != 0, (
            f"type-check-strict завершился с кодом 0 при mypy exit={mypy_rc} — "
            "ненулевой код подавлен, CI не fail-stop. "
            f"Команды: {commands}"
        )


# ────────────────────── P0-06: CVE-гейт не подключён к make ci ──────────────


def _all_targets(mk_path: Path) -> set[str]:
    return {
        ln.split(":", 1)[0]
        for ln in mk_path.read_text(encoding="utf-8").splitlines()
        if ln and not ln[0].isspace() and re.match(r"^[a-z][a-z0-9_-]*:", ln)
    }


def _ci_reaches_cve_gate() -> tuple[bool, str]:
    """`make ci` обязан доходить до CVE-гейта — прямо или через другую цель.

    Прямой вызов `tools/pip_audit_gate.py` в рецепте `ci` — не единственный
    корректный вариант: гейт может быть вынесен в отдельную цель (`cve-gate`)
    и вызван из неё. Цепочка разбирается рекурсивно.
    """
    visited: set[str] = set()

    def walk(target: str) -> bool:
        if target in visited:
            return False
        visited.add(target)
        for mk_path in (PIPELINES_MK, SECURITY_MK, QUALITY_MK):
            if target not in _all_targets(mk_path):
                continue
            recipe = _drop_comments(_expand(_target_recipe(mk_path, target)))
            if "pip_audit_gate" in recipe:
                return True
            for dep in re.findall(r"\$\(MAKE\)\s+([a-z][a-z0-9_-]*)", recipe):
                if walk(dep):
                    return True
            return False
        return False

    return walk("ci"), ", ".join(sorted(visited))


def test_ci_runs_the_cve_gate() -> None:
    """`make ci` обязан запускать CVE-гейт.

    `pip-audit` в make/security.mk подавляется через `|| true`, поэтому
    единственная реальная проверка CVE — `tools/pip_audit_gate.py`.
    До аудита 2026-10-09 она вызывалась только из .github/workflows/security.yml,
    то есть `make ci` не знал про CVE вообще.
    """
    reached, visited = _ci_reaches_cve_gate()

    assert reached, (
        f"`make ci` не доходит до tools/pip_audit_gate.py (просмотрено: {visited}). "
        "При подавленном `pip-audit ... || true` уязвимости зависимостей "
        "проходят молча."
    )


def test_pip_audit_failures_are_not_silently_discarded_in_ci_path() -> None:
    """Если CVE-гейт не подключён — `|| true` подавлять результат нельзя."""
    reached, _ = _ci_reaches_cve_gate()
    suppressed = bool(
        re.search(
            r"\bpip-audit\s+--[^\n]*\|\|\s*true", _target_recipe(SECURITY_MK, "sbom")
        )
    )

    if reached:
        return  # компенсирующий гейт есть — `|| true` оправдан

    assert not suppressed, (
        "`pip-audit` подавлен через `|| true`, а компенсирующий "
        "tools/pip_audit_gate.py не вызывается из `make ci` — "
        "уязвимости зависимостей проходят молча."
    )


# ────────────── P0-08: устаревший отчёт = «зелёный» CVE-гейт ───────────────


def test_audit_deps_does_not_suppress_pip_audit_failure() -> None:
    """`audit-deps` обязан пробрасывать ошибку pip-audit.

    Подавление `|| true` означало: при падении pip-audit (например, из-за
    неразрешимых версий под Python 3.14) новый отчёт не создаётся, но
    `tools/pip_audit_gate.py` читает **прошлый** `dist/pip-audit.json`
    (каталог `dist/` в .gitignore, поэтому файл живёт месяцами) и рапортует
    «PASS: 0 unignored vulnerabilities» по данным недельной давности.
    """
    recipe = _target_recipe(SECURITY_MK, "audit-deps")

    assert not re.search(r"\bpip-audit\s+--[^\n]*\|\|\s*true", recipe), (
        "`audit-deps` подавляет ошибку pip-audit через `|| true`. "
        "Провал сканера = отсутствие свежего отчёта = гейт читает устаревший "
        "dist/pip-audit.json и проходит по старым данным."
    )


def test_audit_deps_removes_stale_report_before_scanning() -> None:
    """Перед сканированием старый отчёт обязан быть удалён.

    Даже при `|| true` удаление гарантирует, что гейт не прочитает отчёт
    предыдущего прогона: если новый не создан — гейт упадёт с «not found».
    """
    recipe = _target_recipe(SECURITY_MK, "audit-deps")

    assert re.search(r"rm\s+-f\s+dist/pip-audit\.json", recipe), (
        "`audit-deps` не удаляет dist/pip-audit.json перед сканом — "
        "устаревший отчёт может быть принят за свежий."
    )


def test_audit_deps_asserts_report_was_produced() -> None:
    """После скана должна быть проверка, что отчёт реально создан."""
    recipe = _target_recipe(SECURITY_MK, "audit-deps")

    assert re.search(r"test\s+-s\s+dist/pip-audit\.json", recipe), (
        "`audit-deps` не проверяет наличие/непустоту dist/pip-audit.json — "
        "успешное сообщение может быть напечатано при пустом отчёте."
    )
