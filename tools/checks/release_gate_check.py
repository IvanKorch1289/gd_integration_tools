#!/usr/bin/env python3
"""Release-gate: агрегация статусов обязательных workflow по SHA.

Заменяет inline-реализацию в ``.github/workflows/release-gate.yml``, которая
была проверена эмпирически (аудит 2026-11-20, эмпирическая часть —
``docs/audit/2026-11-20-audit-factcheck.md`` §3) и содержала три
независимых дефекта:

1. ``/repos/{repo}/actions/runs?head_sha=…&workflow_id=lint.yml`` —
   параметр ``workflow_id`` GitHub **игнорирует**: возвращаются прогоны
   любых workflow, поэтому ``.workflow_runs[0]`` мог принадлежать
   совершенно чужому workflow. Здесь используется документированный
   workflow-specific endpoint
   ``/repos/{repo}/actions/workflows/{workflow_id}/runs`` **плюс**
   обязательная клиентская фильтрация по ``head_sha`` и по пути
   workflow-файла — чужой прогон принять нельзя.
2. Гейт не ждал завершения прогонов: ``jq '.conclusion // "missing"'``
   превращал ``conclusion=null`` (run ещё выполнялся) в ``"missing"`` —
   гейт был красным всегда, даже при полностью зелёных прогонах. Здесь
   прогон в состоянии ``in_progress`` ждёт завершения до жёсткого дедлайна.
3. ``2>/dev/null || echo '{"workflow_runs":[]}'`` смешивала ошибку API с
   «прогона нет» и глушила диагностику. Здесь ошибка API — отдельное
   состояние ``error`` и отдельный код возврата.

Состояния прогона:

* ``success`` — прогон завершён успешно;
* ``failed`` — прогон завершён с неуспешным conclusion;
* ``in_progress`` — прогон ещё выполняется;
* ``missing`` — прогона по этому SHA нет;
* ``error`` — ошибка API или нечитаемый ответ (не ``missing``!).

Коды возврата:

* ``0`` — все обязательные workflow зелёные;
* ``1`` — есть ``failed`` / ``missing`` / не дождались завершения;
* ``2`` — ошибка API или конфигурации (отличается от «проверки красные»).

Запуск::

    python tools/checks/release_gate_check.py --repo owner/name --sha <sha> \\
        --workflows lint.yml test.yml

Токен берётся из ``GH_TOKEN`` / ``GITHUB_TOKEN`` — ``gh`` подхватывает его
сам; ``gh auth login`` тоже подходит.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import quote

EXIT_OK = 0
EXIT_CHECKS_FAILED = 1
EXIT_TOOL_ERROR = 2

#: Жёсткий дедлайн ожидания завершения прогонов, секунды.
DEFAULT_TIMEOUT = 2400.0
#: Интервал опроса прогонов, секунды.
DEFAULT_INTERVAL = 30.0
#: Сколько ждать появления ещё не созданных прогонов (гонка запуска гейта
#: параллельно upstream-workflow), секунды.
DEFAULT_MISSING_GRACE = 600.0
#: Каталог workflow-файлов в репозитории (используется для сверки пути).
WORKFLOWS_DIR = ".github/workflows"
#: Таймаут одного вызова ``gh api``, секунды.
GH_API_TIMEOUT = 60.0
#: Сколько прогонов запрашивать за один раз (перезапуски = отдельные run'ы).
PER_PAGE = 100


class Status(str, Enum):
    """Состояние обязательного workflow по итогам опроса."""

    SUCCESS = "success"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
    MISSING = "missing"
    ERROR = "error"


class ApiError(RuntimeError):
    """Ошибка обращения к GitHub API или нечитаемый ответ."""


@dataclass(frozen=True, slots=True)
class WorkflowState:
    """Состояние одного обязательного workflow."""

    workflow: str
    status: Status
    detail: str = ""
    run_id: int | None = None


@dataclass(frozen=True, slots=True)
class GateResult:
    """Итог опроса обязательных workflow."""

    states: dict[str, WorkflowState]
    timed_out: bool = False

    @property
    def has_error(self) -> bool:
        """Есть ли среди состояний ошибка API.

        Returns:
            ``True``, если хотя бы один workflow не удалось опросить.
        """
        return any(state.status is Status.ERROR for state in self.states.values())

    @property
    def red(self) -> dict[str, WorkflowState]:
        """Неуспешные состояния (без ошибок API).

        Returns:
            Словарь ``workflow → состояние`` для всех не-``success``.
        """
        return {
            workflow: state
            for workflow, state in self.states.items()
            if state.status is not Status.SUCCESS
        }


def _gh_api(url: str) -> str:
    """Выполнить ``gh api`` и вернуть тело ответа.

    Args:
        url: Относительный путь GitHub REST API.

    Returns:
        Тело ответа (текст JSON).

    Raises:
        ApiError: ``gh`` недоступен, завершился с ненулевым кодом или не
            ответил за отведённое время.
    """
    cmd = ["gh", "api", "-H", "Accept: application/vnd.github+json", url]
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированная команда, argv контролируется
            cmd, capture_output=True, text=True, check=False, timeout=GH_API_TIMEOUT
        )
    except FileNotFoundError as exc:
        raise ApiError("gh не найден в PATH — нужен GitHub CLI") from exc
    except subprocess.TimeoutExpired as exc:
        raise ApiError(f"gh api не ответил за {GH_API_TIMEOUT:.0f} с") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise ApiError(
            f"gh api завершился с кодом {proc.returncode}: "
            f"{stderr or 'без вывода в stderr'}. Проверьте токен "
            "(GH_TOKEN/GITHUB_TOKEN) и право 'actions: read'"
        )
    return proc.stdout


def fetch_runs(repo: str, workflow: str, shas: Sequence[str]) -> list[dict[str, Any]]:
    """Получить прогоны конкретного workflow по допустимым SHA.

    Используется документированный workflow-specific endpoint: в общем
    списке прогонов (``/actions/runs``) параметр ``workflow_id``
    игнорируется, а в пути ``/actions/workflows/{workflow_id}/runs``
    учитывается.

    Запрос выполняется по каждому SHA из списка: у события ``merge_group``
    прогоны могут быть записаны и по head-коммиту merge-группы, и по
    временному merge-коммиту, а фильтр API ``head_sha`` допускает
    только одно значение.

    Args:
        repo: Репозиторий в формате ``owner/name``.
        workflow: Имя workflow-файла (например ``lint.yml``).
        shas: Допустимые SHA коммитов.

    Returns:
        Список прогонов — сырые словари из ответа API (без дублей).

    Raises:
        ApiError: Ошибка API или нечитаемый ответ.
    """
    collected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for sha in shas:
        url = (
            f"/repos/{repo}/actions/workflows/{quote(workflow, safe='')}/runs"
            f"?head_sha={quote(sha, safe='')}&per_page={PER_PAGE}"
        )
        payload = _gh_api(url)
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ApiError(f"нечитаемый JSON от gh api: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ApiError("ответ gh api — не JSON-объект")
        runs = parsed.get("workflow_runs")
        if not isinstance(runs, list):
            raise ApiError("в ответе gh api нет списка 'workflow_runs'")
        for run in runs:
            if not isinstance(run, dict):
                continue
            run_id = run.get("id")
            marker = run_id if isinstance(run_id, int) else id(run)
            if marker in seen:
                continue
            seen.add(marker)
            collected.append(run)
    return collected


def _run_attempt(run: dict[str, Any]) -> int:
    """Номер попытки прогона.

    Args:
        run: Прогон из ответа API.

    Returns:
        ``run_attempt`` (1, если поле отсутствует или нечитаемо).
    """
    attempt = run.get("run_attempt")
    return attempt if isinstance(attempt, int) else 1


def _run_id(run: dict[str, Any]) -> int | None:
    """Идентификатор прогона.

    Args:
        run: Прогон из ответа API.

    Returns:
        ``id`` прогона либо ``None``.
    """
    run_id = run.get("id")
    return run_id if isinstance(run_id, int) else None


def select_run(
    runs: Sequence[dict[str, Any]], workflow: str, shas: Sequence[str]
) -> dict[str, Any] | None:
    """Выбрать актуальный прогон workflow для допустимых SHA.

    Фильтры обязательны: прогон чужого SHA или чужого workflow-файла
    не может быть принят за прогон требуемого.

    Допустимых SHA может быть несколько: у события ``merge_group``
    прогоны могут фиксироваться и по head-коммиту merge-группы, и по
    временному merge-коммиту (``github.sha``) — оба принадлежат этому
    же событию, поэтому принимается любой из них. Чужой коммит не
    принимается никогда.

    Args:
        runs: Прогоны из ответа API.
        workflow: Имя workflow-файла.
        shas: Допустимые SHA коммитов.

    Returns:
        Актуальный прогон (последняя попытка) либо ``None``, если
        подходящих прогонов нет.
    """
    expected_path = f"{WORKFLOWS_DIR}/{workflow}"
    allowed = set(shas)
    matching = [
        run
        for run in runs
        if run.get("head_sha") in allowed and run.get("path") == expected_path
    ]
    if not matching:
        return None
    return max(matching, key=lambda run: (_run_attempt(run), _run_id(run) or 0))


def evaluate_run(run: dict[str, Any] | None) -> tuple[Status, str]:
    """Определить состояние прогона.

    Args:
        run: Прогон либо ``None``, если прогона нет.

    Returns:
        Пара ``(состояние, пояснение)``.
    """
    if run is None:
        return Status.MISSING, "прогон для этого SHA не найден"
    status = str(run.get("status") or "")
    if status != "completed":
        return Status.IN_PROGRESS, f"статус прогона: {status or 'unknown'}"
    conclusion = run.get("conclusion")
    if conclusion == "success":
        return Status.SUCCESS, "conclusion: success"
    return Status.FAILED, f"conclusion: {conclusion or 'null'}"


def collect_states(
    repo: str,
    shas: Sequence[str],
    workflows: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    interval: float = DEFAULT_INTERVAL,
    missing_grace: float = DEFAULT_MISSING_GRACE,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> GateResult:
    """Опросить workflow и дождаться завершения выполняющихся прогонов.

    Ожидание идёт, пока хотя бы один прогон в состоянии ``in_progress``;
    жёсткий дедлайн (``timeout``) прерывает ожидание.

    Отдельно обрабатывается гонка запуска: гейт стартует параллельно с
    upstream-workflow, и на первом опросе их прогоны могут ещё не быть
    созданы (``missing``). Отсутствующие прогоны ждут появления в пределах
    ``missing_grace`` — ВСЕГДА, а не только когда «кто-то уже стартовал»:
    гейт может стартовать раньше всех, и ранний выход сделал бы гейт
    структурно красным (независимое ревью 2026-11-23, MINOR-9). Если
    прогоны так и не появились — ``missing`` финален, вердикт — «красный».

    Args:
        repo: Репозиторий в формате ``owner/name``.
        shas: Допустимые SHA коммитов (для merge_group — несколько).
        workflows: Имена обязательных workflow-файлов.
        timeout: Дедлайн ожидания, секунды.
        interval: Интервал опроса, секунды.
        missing_grace: Сколько ждать появления ещё не созданных прогонов,
            секунды.
        sleep_fn: Функция ожидания (подменяется в тестах).
        clock: Источник монотонного времени (подменяется в тестах).

    Returns:
        Итог опроса; ``timed_out`` — ``True``, если дедлайн истёк, пока
        прогон ещё выполнялся.
    """
    deadline = clock() + timeout
    missing_deadline = clock() + missing_grace
    while True:
        states: dict[str, WorkflowState] = {}
        errored = False
        for workflow in workflows:
            try:
                runs = fetch_runs(repo, workflow, shas)
            except ApiError as exc:
                states[workflow] = WorkflowState(
                    workflow=workflow, status=Status.ERROR, detail=str(exc)
                )
                errored = True
                continue
            run = select_run(runs, workflow, shas)
            status, detail = evaluate_run(run)
            states[workflow] = WorkflowState(
                workflow=workflow,
                status=status,
                detail=detail,
                run_id=_run_id(run) if run is not None else None,
            )
        if errored:
            # Ошибка API — не «прогона нет»: останавливаемся и поднимаем её
            # наверх как exit 2, а не маскируем под missing.
            return GateResult(states=states, timed_out=False)
        in_progress = [
            workflow
            for workflow, state in states.items()
            if state.status is Status.IN_PROGRESS
        ]
        missing = [
            workflow
            for workflow, state in states.items()
            if state.status is Status.MISSING
        ]
        if not in_progress and not missing:
            return GateResult(states=states, timed_out=False)
        wait_deadline = deadline if in_progress else missing_deadline
        remaining = wait_deadline - clock()
        if remaining <= 0:
            return GateResult(states=states, timed_out=bool(in_progress))
        sleep_fn(min(interval, remaining))


def render_report(repo: str, shas: Sequence[str], result: GateResult) -> str:
    """Собрать таблицу статусов по workflow.

    Args:
        repo: Репозиторий.
        shas: Допустимые SHA коммитов.
        result: Итог опроса.

    Returns:
        Текст отчёта (по одной строке на workflow).
    """
    lines = [
        f"release-gate: repo={repo} sha={','.join(shas)}",
        f"{'workflow':<20} {'status':<12} detail",
    ]
    for workflow, state in result.states.items():
        run = f"run={state.run_id}" if state.run_id is not None else "run=-"
        lines.append(f"{workflow:<20} {state.status.value:<12} {state.detail} ({run})")
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    *,
    sleep_fn: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы командной строки (по умолчанию ``sys.argv[1:]``).
        sleep_fn: Функция ожидания между опросами (подменяется в тестах).
        clock: Источник монотонного времени (подменяется в тестах).

    Returns:
        0 — все workflow зелёные; 1 — проверки красные (failed / missing /
        не дождались завершения); 2 — ошибка API или конфигурации.
    """
    parser = argparse.ArgumentParser(
        description="Агрегация статусов обязательных workflow по SHA"
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="Репозиторий owner/name (по умолчанию env GITHUB_REPOSITORY)",
    )
    parser.add_argument(
        "--sha",
        default=os.environ.get("GITHUB_SHA"),
        help=(
            "SHA коммита (по умолчанию env GITHUB_SHA). Можно указать несколько "
            "через запятую: у merge_group прогоны фиксируются и по head-коммиту "
            "merge-группы, и по временному merge-коммиту — оба принадлежат "
            "событию. В CI для pull_request GITHUB_SHA — merge-коммит, поэтому "
            "workflow передаёт --sha явно (head-коммит PR)"
        ),
    )
    parser.add_argument(
        "--workflows",
        nargs="+",
        default=[],
        help="Имена обязательных workflow-файлов (например lint.yml test.yml)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Дедлайн ожидания завершения, секунды (по умолчанию {DEFAULT_TIMEOUT:.0f})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"Интервал опроса, секунды (по умолчанию {DEFAULT_INTERVAL:.0f})",
    )
    parser.add_argument(
        "--missing-grace",
        type=float,
        default=DEFAULT_MISSING_GRACE,
        help=(
            "Сколько ждать появления ещё не созданных прогонов (секунды). "
            f"По умолчанию {DEFAULT_MISSING_GRACE:.0f}. Применяется всегда: "
            "гейт может стартовать раньше upstream-workflow, и ранний выход "
            "сделал бы гейт структурно красным"
        ),
    )
    args = parser.parse_args(argv)

    if not args.repo:
        print("ОШИБКА: не указан --repo (или env GITHUB_REPOSITORY)", file=sys.stderr)
        return EXIT_TOOL_ERROR
    shas = [item.strip() for item in args.sha.split(",") if item.strip()]
    if not shas:
        print("ОШИБКА: не указан --sha (или env GITHUB_SHA)", file=sys.stderr)
        return EXIT_TOOL_ERROR
    if not args.workflows:
        print(
            "ОШИБКА: не указан --workflows (список имён workflow-файлов)",
            file=sys.stderr,
        )
        return EXIT_TOOL_ERROR
    bad = [wf for wf in args.workflows if not wf.endswith((".yml", ".yaml"))]
    if bad:
        print(
            f"ОШИБКА: не имена workflow-файлов: {', '.join(bad)} "
            "(GitHub API принимает ID или имя файла, а не имя job'а)",
            file=sys.stderr,
        )
        return EXIT_TOOL_ERROR

    result = collect_states(
        args.repo,
        shas,
        args.workflows,
        timeout=args.timeout,
        interval=args.interval,
        missing_grace=args.missing_grace,
        sleep_fn=sleep_fn if sleep_fn is not None else time.sleep,
        clock=clock if clock is not None else time.monotonic,
    )
    print(render_report(args.repo, shas, result))

    if result.has_error:
        print("ОШИБКА API — статус прогонов определить не удалось:", file=sys.stderr)
        for workflow, state in result.states.items():
            if state.status is Status.ERROR:
                print(f"  - {workflow}: {state.detail}", file=sys.stderr)
        return EXIT_TOOL_ERROR

    if result.timed_out:
        pending = [
            workflow
            for workflow, state in result.states.items()
            if state.status is Status.IN_PROGRESS
        ]
        print(
            f"НЕ ДОЖДАЛИСЬ завершения прогонов за {args.timeout:.0f} с: "
            f"{', '.join(pending)}",
            file=sys.stderr,
        )
        return EXIT_CHECKS_FAILED

    red = result.red
    if red:
        print(
            "RELEASE GATE FAILED — обязательные workflow не зелёные:", file=sys.stderr
        )
        for workflow, state in red.items():
            print(
                f"  - {workflow}: {state.status.value} ({state.detail})",
                file=sys.stderr,
            )
        return EXIT_CHECKS_FAILED

    print("RELEASE GATE PASS — все обязательные workflow зелёные")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
