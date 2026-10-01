"""F-Z meta-гейт: сам release-gate.yml должен быть непротиворечив.

Аудит 2026-10-01 доказал, что ``.github/workflows/release-gate.yml`` падал с
exit 1 при **любом** SHA из-за двух независимых дефектов, каждый из которых
не обнаруживается ни одним существующим гейтом:

1. ``REPO`` использовалась в ``gh api`` под ``set -u``, но нигде не была
   объявлена → первый вызов падал «unbound variable», до самой агрегации;
2. в ``REQUIRED`` стоял ``build-and-deploy`` — это имя job'а из
   ``docs-publish.yml``, а не workflow-файл. Контейнерный pipeline живёт в
   ``image.yml`` → ``workflow_runs`` всегда пуст → ``conclusion: missing``.

Оба класса дефектов статически проверяемы, поэтому закрываются здесь, а не
в GitHub Actions.

Проверки:
    * ``release-gate.yml`` существует и парсится;
    * все идентификаторы из ``REQUIRED`` — существующие файлы ``.github/workflows/``
      (ловит «имя job'а/``name:``» вместо имени файла);
    * каждый требуемый workflow триггерится на ``pull_request`` — иначе для
      SHA из PR не будет run'а и гейт не сможет пройти никогда;
    * все ``${VAR}`` в ``run:``-скрипте объявлены в ``env:`` (workflow/job/step),
      присвоены в самом скрипте или принадлежат раннеру — ловит F-Z.1.

Известное ограничение (намеренно не «полный shell-парсер»): разбираются
только присваивания, ``for``/``local``/``export``/``declare``/``read`` и
позиционные параметры игнорируются. Динамические обращения вида
``${!name}`` или ``eval`` не отслеживаются — гейт ловит прямой класс F-Z,
а не произвольные shell-конструкции.

Usage:
    python tools/checks/check_release_gate.py [--workflows-dir .github/workflows]

Exit codes:
    0 — гейт непротиворечив;
    1 — FAIL (найдены нарушения, перечислены в выводе);
    2 — TOOL_FAILURE (файл отсутствует или не парсится) — отделено от
        кодовых нарушений, чтобы падение инструмента не читалось как FAIL.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_GATE: Path = ROOT / ".github" / "workflows" / "release-gate.yml"
DEFAULT_WORKFLOWS_DIR: Path = ROOT / ".github" / "workflows"

#: Расширения, которые GitHub Actions считает workflow-файлами.
WORKFLOW_SUFFIXES: frozenset[str] = frozenset({".yml", ".yaml"})

#: Переменные, которые раннер/GitHub выставляет сам (docs.github.com
#: «Store information in variables» + базовый POSIX-набор bash).
RUNNER_PROVIDED: frozenset[str] = frozenset(
    {
        "BASH_ENV",
        "CI",
        "HOME",
        "HOSTNAME",
        "PATH",
        "PWD",
        "SHELL",
        "SHLVL",
        "TMPDIR",
        "USER",
        "_",
    }
)
RUNNER_PROVIDED_PREFIXES: tuple[str, ...] = ("GITHUB_", "RUNNER_", "ACTIONS_")

#: `NAME=`, `export NAME=`, `local NAME=`, `declare -a NAME=`
_ASSIGN_RE = re.compile(
    r"^\s*(?:export\s+|local\s+|declare\s+(?:-\w+\s+)*|typeset\s+(?:-\w+\s+)*)?"
    r"([A-Za-z_][A-Za-z0-9_]*)=",
    re.MULTILINE,
)
#: `for NAME in ...`
_FOR_RE = re.compile(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b", re.MULTILINE)
#: `while read NAME`, `read -r NAME`
_READ_RE = re.compile(r"\bread\s+(?:-\w+\s+)*([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
#: `${NAME}` и `$NAME` (позиционные `$1`/`$?`/`$@` отсекаются классом символов)
_EXPAND_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
#: Элемент списка `REQUIRED=( ... )`
_REQUIRED_BLOCK_RE = re.compile(r"^\s*REQUIRED=\((.*?)\)", re.DOTALL | re.MULTILINE)
_LIST_ITEM_RE = re.compile(r'"([^"]+)"')
#: Вызов `set` — флаги могут быть кластером (`set -euo pipefail`)
_SET_RE = re.compile(r"^\s*set\s+(--?[^\s]+)(.*)$", re.MULTILINE)


def _script_uses_nounset(script: str) -> bool:
    """Включён ли ``set -u`` / ``set -o nounset``.

    Флаги ``set`` образуют кластер: в ``set -euo pipefail`` буква ``u`` не
    является подстрокой ``-euo``, поэтому опции разбираются посимвольно.
    Длинная форма ``--nounset`` и ``-o nounset`` учтены отдельно.

    Args:
        script: Текст shell-скрипта из ``run:``.

    Returns:
        ``True``, если неопределённая переменная приведёт к падению скрипта.
    """
    for match in _SET_RE.finditer(script):
        flag, rest = match.group(1), match.group(2)
        if flag.startswith("--"):
            if flag == "--nounset":
                return True
            continue
        if flag.startswith("-o") and "nounset" in rest:
            return True
        if flag.startswith("-") and "u" in flag[1:]:
            return True
    return False


def _on_key(doc: dict[str, Any]) -> Any:
    """Вернуть значение ключа ``on`` с учётом YAML 1.1 ``on → True``.

    PyYAML реализует YAML 1.1, где неquoted ``on`` — булева ``True``.
    GitHub Actions использует YAML 1.2 и ждёт строку ``on``.

    Args:
        doc: Разобранный workflow.

    Returns:
        Значение триггеров либо ``None``, если ключ не найден.
    """
    if "on" in doc:
        return doc["on"]
    return doc.get(True)


def _triggers_pull_request(doc: dict[str, Any]) -> bool:
    """Есть ли у workflow триггер ``pull_request``.

    Args:
        doc: Разобранный workflow.

    Returns:
        ``True``, если workflow запускается на pull_request.
    """
    on = _on_key(doc)
    if isinstance(on, str):
        return on == "pull_request"
    if isinstance(on, list):
        return "pull_request" in on
    if isinstance(on, dict):
        return "pull_request" in on
    return False


def _collect_env(*scopes: Any) -> set[str]:
    """Собрать имена переменных из ``env:``-словарей.

    Args:
        *scopes: Словари ``env`` уровня workflow / job / step (могут быть ``None``).

    Returns:
        Множество объявленных имён переменных.
    """
    names: set[str] = set()
    for scope in scopes:
        if isinstance(scope, dict):
            names.update(str(key) for key in scope)
    return names


def _iter_run_scripts(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Собрать пары ``(job_name, script)`` для всех ``run:``-шагов.

    Args:
        doc: Разобранный workflow.

    Returns:
        Список пар: имя job'а и текст его скрипта (только ``run:``-шаги).
    """
    pairs: list[tuple[str, dict[str, Any]]] = []
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return pairs
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                pairs.append((str(job_name), step))
    return pairs


def check_gate(gate: Path, workflows_dir: Path) -> list[str]:
    """Проверить непротиворечивость release-gate.

    Args:
        gate: Путь к ``release-gate.yml``.
        workflows_dir: Каталог с workflow-файлами.

    Returns:
        Список нарушений; пустой список — гейт корректен.

    Raises:
        FileNotFoundError: ``gate`` не существует.
        ValueError: ``gate`` не является YAML-маппингом.
    """
    if not gate.is_file():
        raise FileNotFoundError(gate)
    doc = yaml.safe_load(gate.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{gate}: ожидался YAML-маппинг, получен {type(doc).__name__}")

    violations: list[str] = []

    scripts = _iter_run_scripts(doc)
    if not scripts:
        violations.append("release-gate.yml не содержит ни одного run:-шага")

    block = _REQUIRED_BLOCK_RE.search(gate.read_text(encoding="utf-8"))
    if block is None:
        violations.append("не найден список REQUIRED=(...) в run:-скрипте")
        required: list[str] = []
    else:
        required = _LIST_ITEM_RE.findall(block.group(1))

    # 1–3. REQUIRED: расширение, существование файла, триггер pull_request.
    for workflow_id in required:
        if Path(workflow_id).suffix not in WORKFLOW_SUFFIXES:
            violations.append(
                f"REQUIRED[{workflow_id!r}]: не имя workflow-файла. "
                f"GitHub API принимает ID или имя файла (.yml/.yaml), "
                f"не имя job'а и не значение 'name:'"
            )
            continue
        path = workflows_dir / workflow_id
        if not path.is_file():
            violations.append(
                f"REQUIRED[{workflow_id!r}]: файла нет в {workflows_dir.name}/ — "
                f"gh api вернёт пустой workflow_runs → conclusion 'missing' → гейт всегда FAIL"
            )
            continue
        upstream = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(upstream, dict) and not _triggers_pull_request(upstream):
            violations.append(
                f"REQUIRED[{workflow_id!r}]: workflow не триггерится на pull_request — "
                f"для SHA из PR не будет run'а, гейт не сможет пройти"
            )

    # 4. Необъявленные переменные под `set -u`.
    for job_name, step in scripts:
        script = step["run"]
        if not _script_uses_nounset(script):
            continue
        declared = _collect_env(
            doc.get("env"), _job_env(doc, job_name), step.get("env")
        )
        assigned = {
            *{m.group(1) for m in _ASSIGN_RE.finditer(script)},
            *{m.group(1) for m in _FOR_RE.finditer(script)},
            *{m.group(1) for m in _READ_RE.finditer(script)},
        }
        used: set[str] = set()
        for match in _EXPAND_RE.finditer(script):
            used.add(match.group(1) or match.group(2))
        for name in sorted(used - declared - assigned):
            if name in RUNNER_PROVIDED or name.startswith(RUNNER_PROVIDED_PREFIXES):
                continue
            violations.append(
                f"job '{job_name}': переменная ${{{name}}} используется под `set -u`, "
                f"но не объявлена в env: и не присвоена в скрипте → "
                f"bash завершится 'unbound variable' до агрегации"
            )

    return violations


def _job_env(doc: dict[str, Any], job_name: str) -> Any:
    """Вернуть ``env:``-словарь конкретного job'а.

    Args:
        doc: Разобранный workflow.
        job_name: Имя job'а.

    Returns:
        ``env`` job'а либо ``None``.
    """
    job = (doc.get("jobs") or {}).get(job_name)
    return job.get("env") if isinstance(job, dict) else None


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы командной строки (по умолчанию ``sys.argv[1:]``).

    Returns:
        0 — нарушений нет; 1 — нарушения найдены; 2 — инструментальная ошибка.
    """
    parser = argparse.ArgumentParser(
        description="Проверка непротиворечивости release-gate.yml"
    )
    parser.add_argument(
        "--gate", type=Path, default=DEFAULT_GATE, help="Путь к release-gate.yml"
    )
    parser.add_argument(
        "--workflows-dir",
        type=Path,
        default=DEFAULT_WORKFLOWS_DIR,
        help="Каталог с workflow-файлами",
    )
    args = parser.parse_args(argv)

    try:
        violations = check_gate(args.gate, args.workflows_dir)
    except FileNotFoundError as exc:
        print(f"TOOL_FAILURE: файл не найден: {exc}", file=sys.stderr)
        return 2
    except (ValueError, yaml.YAMLError) as exc:
        print(f"TOOL_FAILURE: не удалось разобрать {args.gate}: {exc}", file=sys.stderr)
        return 2

    if violations:
        print(f"❌ release-gate: {len(violations)} нарушение(й)")
        for item in violations:
            print(f"  - {item}")
        return 1

    print(
        "✅ release-gate: REQUIRED разрешаются в существующие workflow-файлы, $VAR объявлены"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
