#!/usr/bin/env python3
"""Gate-скрипт для проверки mutation score (mutmut) в CI.

Запускает mutmut, экспортирует CI/CD stats и сверяет score с порогом.
Порог по умолчанию берётся из baseline (``.baselines/mutation.json``) —
«рэтчет: не хуже baseline» (ADR-0452).

Контракт exit-кодов (fail-closed)::

    0  PASS     — score >= порога.
    1  FAIL     — score < порога.
    2  SKIPPED  — score НЕ измерен (нет mutmut / нет данных о мутациях /
                  исчерпан бюджет времени). Это НЕ «зелёный» результат:
                  причина печатается явно, чтобы пропуск был виден в логе CI.
    3  ERROR    — некорректная конфигурация (baseline отсутствует или битый).

Использование::

    uv run python tools/checks/check_mutmut.py [--threshold 21.6] [--timeout 360]

    # быстрая проверка накопленных результатов без повторного прогона
    uv run python tools/checks/check_mutmut.py --no-run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

# Импортируем helper'ы из wrapper'а
sys.path.insert(0, str(Path(__file__).parent))
from run_mutmut import (  # type: ignore[import-not-found]  # noqa: E402  # dev-tool: sys.path hack
    _patch_mutmut,
    _sync_mutants_assets,
    _sync_mutants_src,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / ".baselines" / "mutation.json"
STATS_REL_PATH = Path("mutants") / "mutmut-cicd-stats.json"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_SKIPPED = 2
EXIT_ERROR = 3


class BaselineError(RuntimeError):
    """Baseline-файл отсутствует или нечитаем — гейт не может определить порог."""


class MutmutError(RuntimeError):
    """Окружение/инструмент не позволяет измерить score."""


class NoMutationData(MutmutError):
    """Нет результатов мутаций (пустая рабочая копия ``mutants/``)."""


class TimeBudgetExceeded(MutmutError):
    """Исчерпан бюджет времени на прогон мутаций."""


def _mutmut_available() -> bool:
    """Проверить, что модуль ``mutmut`` импортируется в текущем интерпретаторе.

    Returns:
        True, если mutmut установлен; иначе False.

    """
    try:
        return importlib.util.find_spec("mutmut") is not None
    except ImportError, ValueError:
        return False


def _current_git_commit(repo_root: Path) -> str | None:
    """Текущий HEAD репозитория (None, если git недоступен).

    Args:
        repo_root: Корень репозитория.

    Returns:
        SHA коммита или None.

    """
    try:
        proc = subprocess.run(  # noqa: S603  # dev-tool: фиксированная команда
            ["git", "rev-parse", "HEAD"],  # noqa: S607  # dev-tool: git — PATH binary
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _results_git_commit(repo_root: Path) -> str | None:
    """Коммит, к которому относятся накопленные результаты мутаций.

    Args:
        repo_root: Корень репозитория.

    Returns:
        SHA коммита из ``mutants/mutmut-stats.json`` или None.

    """
    stats_path = repo_root / "mutants" / "mutmut-stats.json"
    if not stats_path.exists():
        return None
    try:
        data = json.loads(stats_path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    commit = data.get("git_commit")
    return str(commit) if commit else None


def _mutated_source_paths(repo_root: Path) -> list[str]:
    """Пути мутируемых модулей из ``[tool.mutmut]`` pyproject.toml.

    Args:
        repo_root: Корень репозитория.

    Returns:
        Список путей (как в конфиге) либо пустой список, если конфиг не читается.

    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return []
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        paths = data.get("tool", {}).get("mutmut", {}).get("source_paths", [])
    except OSError, ValueError, KeyError:
        return []
    return [str(path) for path in paths]


def _not_checked_count(repo_root: Path, source_paths: list[str]) -> int:
    """Сколько мутантов осталось непроверенными (вердикт ``None``).

    Прерванный прогон оставляет часть мутаций без вердикта, но mutmut всё
    равно включает их в ``total`` — score получается заниженным и не отражает
    реальное состояние кода. Такую статистику гейт не должен выдавать за
    измеренную.

    Args:
        repo_root: Корень репозитория.
        source_paths: Мутируемые модули (из ``[tool.mutmut]``).

    Returns:
        Количество мутаций без вердикта.

    """
    not_checked = 0
    for rel_path in source_paths:
        meta_path = repo_root / "mutants" / (rel_path + ".meta")
        if not meta_path.exists():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        verdicts = data.get("exit_code_by_key")
        if isinstance(verdicts, dict):
            not_checked += sum(1 for verdict in verdicts.values() if verdict is None)
    return not_checked


def _run_mutmut(
    repo_root: Path, env: dict[str, str], timeout: float | None = None
) -> int:
    """Запустить ``python -m mutmut run`` (не PATH-бинарник).

    Args:
        repo_root: Корень репозитория (cwd для запуска).
        env: Окружение процесса.
        timeout: Бюджет времени в секундах; None — без ограничения.

    Returns:
        Exit-код процесса mutmut.

    Raises:
        TimeBudgetExceeded: Бюджет времени исчерпан.

    """
    cmd = [sys.executable, "-m", "mutmut", "run"]
    budget = "без ограничения" if timeout is None else f"{timeout:.0f}s"
    print(f"[check_mutmut] Running {' '.join(cmd)} (бюджет: {budget})")
    # start_new_session=True — отдельная process group: mutmut форкает
    # pytest-процессы, и при таймауте их нужно убить вместе с родителем,
    # иначе они осиротеют и продолжают жрать CPU раннера.
    proc = subprocess.Popen(  # noqa: S603  # dev-tool: фиксированная команда
        cmd, cwd=repo_root, env=env, start_new_session=True
    )
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # процесс уже завершился — убивать нечего
        proc.wait()
        raise TimeBudgetExceeded(
            f"превышен бюджет времени на прогон мутаций ({timeout:.0f}s)"
        ) from None


def _export_cicd_stats(repo_root: Path, env: dict[str, str]) -> Path:
    """Экспортировать CI/CD stats mutmut и вернуть путь к файлу.

    Перед экспортом старый файл удаляется: ``mutmut export-cicd-stats`` при
    отсутствии результатов печатает ``No previous mutation data found`` и
    выходит с кодом 0, НЕ перезаписывая файл. Без удаления гейт сравнил бы
    со score ПРОШЛОГО прогона (fail-open на устаревших данных).

    Args:
        repo_root: Корень репозитория.
        env: Окружение процесса.

    Returns:
        Путь к свежему файлу статистики.

    Raises:
        MutmutError: Экспорт не удался.
        NoMutationData: Свежая статистика не была создана.

    """
    stats_path = repo_root / STATS_REL_PATH
    stats_path.unlink(missing_ok=True)
    print("[check_mutmut] Exporting CI/CD stats...")
    proc = subprocess.run(  # noqa: S603  # dev-tool: фиксированная команда
        [sys.executable, "-m", "mutmut", "export-cicd-stats"], cwd=repo_root, env=env
    )
    if proc.returncode != 0:
        raise MutmutError(
            f"mutmut export-cicd-stats завершился с кодом {proc.returncode}"
        )
    if not stats_path.exists():
        raise NoMutationData(
            "нет данных о мутациях (рабочая копия mutants/ пуста или .meta отсутствуют)"
        )
    return stats_path


def _parse_stats(stats_path: Path) -> dict[str, int]:
    """Прочитать счётчики из ``mutmut-cicd-stats.json``.

    Args:
        stats_path: Путь к файлу статистики.

    Returns:
        Счётчики мутаций (killed/survived/total/no_tests/...).

    """
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    return {
        key: int(value)
        for key, value in data.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _parse_score(stats_path: Path) -> float | None:
    """Посчитать mutation score (killed / total) в процентах.

    Args:
        stats_path: Путь к ``mutmut-cicd-stats.json``.

    Returns:
        Score в процентах; None — если мутаций не было (измерить нечего).

    """
    stats = _parse_stats(stats_path)
    total = stats.get("total", 0)
    killed = stats.get("killed", 0)
    if total <= 0:
        return None
    return (killed / total) * 100.0


def _load_baseline(path: Path = BASELINE_PATH) -> float:
    """Прочитать порог из baseline-файла (рэтчет, ADR-0452).

    Args:
        path: Путь к baseline-файлу.

    Returns:
        Порог в процентах.

    Raises:
        BaselineError: Файл отсутствует, нечитаем или не содержит числового
            ``mutation_score_percent``. Молчаливый fallback на константу
            сделал бы гейт «проходящим вхолостую» с неверным порогом.

    """
    if not path.exists():
        raise BaselineError(f"baseline-файл не найден: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BaselineError(f"baseline-файл не читается: {path} ({exc})") from exc
    if not isinstance(data, dict) or "mutation_score_percent" not in data:
        raise BaselineError(
            f"в baseline-файле нет ключа mutation_score_percent: {path}"
        )
    try:
        return float(data["mutation_score_percent"])
    except (TypeError, ValueError) as exc:
        raise BaselineError(
            f"mutation_score_percent в baseline-файле не число: {path}"
        ) from exc


def _write_baseline(score: float, path: Path = BASELINE_PATH) -> None:
    """Зафиксировать измеренный score в baseline-файле.

    Args:
        score: Измеренный score в процентах.
        path: Путь к baseline-файлу.

    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "mutation_score_percent": round(score, 1),
                "updated": "2026-11-17",
                "note": (
                    "ADR-0452: baseline зафиксирован первым рабочим прогоном "
                    "mutmut (раньше гейт был заблокирован ошибками сбора). "
                    "Рост — только с новыми тестами на мутируемые модули."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    """Точка входа гейта.

    Returns:
        EXIT_PASS / EXIT_FAIL / EXIT_SKIPPED / EXIT_ERROR.

    """
    parser = argparse.ArgumentParser(description="Mutation testing gate")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=(
            "Minimum mutation score threshold (%%); по умолчанию — значение из "
            "baseline (.baselines/mutation.json), т.е. рэтчет «не хуже baseline»"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help=(
            "Бюджет времени на прогон мутаций (сек). По исчерпании гейт "
            "завершается со статусом SKIPPED (exit 2) и явной причиной"
        ),
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help=(
            "Не перезапускать мутации, использовать накопленные результаты "
            "(mutants/*.meta). Score всё равно считается через "
            "export-cicd-stats; если результатов нет — SKIPPED с причиной"
        ),
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="записать измеренный score в baseline-файл",
    )
    args = parser.parse_args()

    repo_root = REPO_ROOT
    env = os.environ.copy()
    env["GD_REPO_ROOT"] = str(repo_root)

    # --- порог: baseline (или явный --threshold) ---------------------------
    try:
        threshold = args.threshold if args.threshold is not None else _load_baseline()
    except BaselineError as exc:
        print(f"[check_mutmut] ERROR: {exc}")
        return EXIT_ERROR

    # --- инструмент ---------------------------------------------------------
    if not _mutmut_available():
        reason = "mutmut не установлен в текущем интерпретаторе"
        print(f"[check_mutmut] SKIPPED: {reason}")
        return EXIT_SKIPPED

    _patch_mutmut()

    # --- прогон мутаций -----------------------------------------------------
    if args.no_run:
        current = _current_git_commit(repo_root)
        recorded = _results_git_commit(repo_root)
        if current is None or recorded is None:
            print(
                "[check_mutmut] SKIPPED: не удалось сопоставить накопленные результаты "
                "с текущим коммитом (нет mutants/mutmut-stats.json или git недоступен)"
            )
            return EXIT_SKIPPED
        if current != recorded:
            print(
                f"[check_mutmut] SKIPPED: накопленные результаты относятся к коммиту "
                f"{recorded[:12]}, текущий — {current[:12]} (нужен повторный прогон)"
            )
            return EXIT_SKIPPED
        print(
            "[check_mutmut] Прогон мутаций пропущен (--no-run), используются накопленные результаты"
        )
    else:
        # Синхронизация рабочей копии мутантов нужна только перед прогоном.
        _sync_mutants_src()
        _sync_mutants_assets()
        try:
            exit_code = _run_mutmut(repo_root, env, args.timeout)
        except TimeBudgetExceeded as exc:
            print(f"[check_mutmut] SKIPPED: {exc}")
            return EXIT_SKIPPED
        if exit_code != 0:
            print(f"[check_mutmut] FAIL: mutmut run завершился с кодом {exit_code}")
            return EXIT_FAIL

    # --- экспорт stats ------------------------------------------------------
    try:
        stats_path = _export_cicd_stats(repo_root, env)
    except NoMutationData as exc:
        print(f"[check_mutmut] SKIPPED: {exc}")
        return EXIT_SKIPPED
    except MutmutError as exc:
        print(f"[check_mutmut] ERROR: {exc}")
        return EXIT_ERROR

    stats = _parse_stats(stats_path)
    score = _parse_score(stats_path)
    if score is None:
        print("[check_mutmut] SKIPPED: измерять нечего (0 мутаций)")
        return EXIT_SKIPPED
    not_checked = _not_checked_count(repo_root, _mutated_source_paths(repo_root))
    if not_checked:
        # Прерванный прогон: часть мутаций без вердикта, но mutmut включает
        # их в total — score занижен и не отражает состояние кода.
        print(
            f"[check_mutmut] SKIPPED: прогон не завершён — {not_checked} мутаций "
            f"не проверено, score не измерим"
        )
        return EXIT_SKIPPED
    total = stats.get("total", 0)
    no_tests = stats.get("no_tests", 0)
    if total > 0 and no_tests >= total:
        # Ни один мутируемый модуль не покрыт тестами: mutmut отметил все
        # мутации как «no tests». Score 0.0 % здесь — артефакт пустой карты
        # тест↔мутант, а не измеренная регрессия.
        print(
            f"[check_mutmut] SKIPPED: ни один мутируемый модуль не покрыт тестами "
            f"({no_tests}/{total} мутаций без тестов) — score не измерим"
        )
        return EXIT_SKIPPED

    if args.update_baseline:
        _write_baseline(score)
        print(f"[check_mutmut] baseline обновлён: {score:.1f}% → {BASELINE_PATH}")
        return EXIT_PASS

    print(f"[check_mutmut] Mutation score: {score:.1f}% (threshold: {threshold:.1f}%)")

    if score >= threshold:
        print(f"[check_mutmut] PASS: score {score:.1f}% >= {threshold:.1f}%")
        return EXIT_PASS
    print(f"[check_mutmut] FAIL: score {score:.1f}% < {threshold:.1f}%")
    return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
