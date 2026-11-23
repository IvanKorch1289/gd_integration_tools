"""Тесты ``tools/checks/release_gate_check.py`` — агрегация статусов workflow.

Дефекты, закрытые этим файлом (аудит 2026-11-20, эмпирическая часть —
``docs/audit/2026-11-20-audit-factcheck.md`` §3):

1. ``/actions/runs?workflow_id=…`` игнорирует ``workflow_id`` — гейт брал
   прогон чужого workflow. Здесь проверяется, что используется
   workflow-specific endpoint и что прогон чужого SHA / чужого пути
   workflow-файла не принимается.
2. Гейт не ждал завершения прогонов и превращал ``conclusion=null`` в
   ``"missing"`` — гейт был красным всегда. Здесь проверяется ожидание
   ``in_progress`` до успеха и внятная ошибка по истечении дедлайна.
3. ``2>/dev/null || echo '{"workflow_runs":[]}'`` смешивал ошибку API с
   «прогона нет». Здесь ошибка API даёт отдельный код возврата 2 и
   **не** трактуется как ``missing``.

Сеть не используется: ``subprocess.run`` подменяется, часы и ожидание —
тоже.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from checks import release_gate_check as gate

pytestmark = pytest.mark.unit

REPO = "owner/repo"
SHA = "a" * 40
OTHER_SHA = "b" * 40


def _ok(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    """Успешный ответ ``gh api``.

    Args:
        payload: Тело ответа.

    Returns:
        Готовый ``CompletedProcess`` с кодом 0.
    """
    return subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout=json.dumps(payload), stderr=""
    )


def _api_error(
    stderr: str = "gh: HTTP 403: Forbidden",
) -> subprocess.CompletedProcess[str]:
    """Ответ ``gh api`` с ошибкой.

    Args:
        stderr: Текст ошибки.

    Returns:
        Готовый ``CompletedProcess`` с ненулевым кодом.
    """
    return subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr=stderr
    )


def _runs(*runs: dict[str, Any]) -> dict[str, Any]:
    """Тело ответа со списком прогонов.

    Args:
        *runs: Прогоны.

    Returns:
        JSON-совместимый словарь ответа API.
    """
    return {"total_count": len(runs), "workflow_runs": list(runs)}


def _run(
    workflow: str,
    sha: str,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: int = 1,
    attempt: int = 1,
    path: str | None = None,
) -> dict[str, Any]:
    """Собрать прогон workflow.

    Args:
        workflow: Имя workflow-файла.
        sha: SHA коммита прогона.
        status: Статус прогона.
        conclusion: Conclusion прогона.
        run_id: Идентификатор прогона.
        attempt: Номер попытки (``run_attempt``).
        path: Путь workflow-файла (по умолчанию ``.github/workflows/<file>``).

    Returns:
        Словарь прогона в формате GitHub API.
    """
    return {
        "id": run_id,
        "name": workflow.removesuffix(".yml"),
        "path": path if path is not None else f".github/workflows/{workflow}",
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
    }


class FakeGh:
    """Подмена ``subprocess.run`` для вызовов ``gh api``."""

    def __init__(
        self, handler: Callable[[str], subprocess.CompletedProcess[str]]
    ) -> None:
        """Запомнить обработчик и журнал вызовов.

        Args:
            handler: Функция ``url → CompletedProcess``.
        """
        self._handler = handler
        self.urls: list[str] = []

    def __call__(
        self, cmd: list[str], *args: Any, **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        """Подменить запуск ``gh api``.

        Args:
            cmd: Команда (последний элемент — URL).
            *args: Прочие позиционные аргументы (не используются).
            **kwargs: Прочие именованные аргументы (не используются).

        Returns:
        Подготовленный ответ.
        """
        url = str(cmd[-1])
        self.urls.append(url)
        return self._handler(url)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Подменить ``subprocess.run`` в модуле гейта.

        Args:
            monkeypatch: Фикстура pytest.
        """
        monkeypatch.setattr(gate.subprocess, "run", self)


class FakeClock:
    """Монотонные часы и ожидание без реального времени."""

    def __init__(self) -> None:
        """Создать часы с нулевым временем."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        """Текущее время.

        Returns:
            Значение счётчика времени.
        """
        return self.now

    def sleep(self, seconds: float) -> None:
        """«Уснуть», сдвинув время.

        Args:
            seconds: Длительность паузы.
        """
        self.sleeps.append(seconds)
        self.now += seconds


def _by_workflow(
    mapping: dict[str, dict[str, Any] | subprocess.CompletedProcess[str]],
) -> Callable[[str], subprocess.CompletedProcess[str]]:
    """Обработчик, раздающий ответы по имени workflow-файла.

    Args:
        mapping: Имя workflow-файла → тело ответа или готовый ``CompletedProcess``.

    Returns:
        Функция ``url → CompletedProcess``.
    """

    def handler(url: str) -> subprocess.CompletedProcess[str]:
        for workflow, payload in mapping.items():
            if f"/actions/workflows/{workflow}/runs" in url:
                if isinstance(payload, subprocess.CompletedProcess):
                    return payload
                return _ok(payload)
        raise AssertionError(f"неожиданный URL: {url}")

    return handler


def _install(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, dict[str, Any] | subprocess.CompletedProcess[str]],
) -> FakeGh:
    """Установить подмену ``gh api``.

    Args:
        monkeypatch: Фикстура pytest.
        mapping: Ответы по именам workflow-файлов.

    Returns:
        Подмена для проверки вызовов.
    """
    fake = FakeGh(_by_workflow(mapping))
    fake.install(monkeypatch)
    return fake


# ── 1. Все workflow зелёные ────────────────────────────────────────────


def test_all_success_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Все обязательные workflow успешны → exit 0.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(
        monkeypatch,
        {
            "lint.yml": _runs(_run("lint.yml", SHA)),
            "test.yml": _runs(_run("test.yml", SHA, run_id=2)),
        },
    )
    code = gate.main(
        ["--repo", REPO, "--sha", SHA, "--workflows", "lint.yml", "test.yml"]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "RELEASE GATE PASS" in captured.out
    assert "lint.yml" in captured.out
    assert "test.yml" in captured.out


# ── 2. Один workflow упал ──────────────────────────────────────────────


def test_failed_workflow_exits_one_and_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Упавший workflow → exit 1, в выводе видно какой именно.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(
        monkeypatch,
        {
            "lint.yml": _runs(_run("lint.yml", SHA)),
            "test.yml": _runs(_run("test.yml", SHA, conclusion="failure", run_id=2)),
        },
    )
    code = gate.main(
        ["--repo", REPO, "--sha", SHA, "--workflows", "lint.yml", "test.yml"]
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "test.yml" in captured.out
    assert "failed" in captured.out
    assert "test.yml: failed" in captured.err


# ── 3. Прогона нет ─────────────────────────────────────────────────────


def test_missing_workflow_exits_one_with_missing_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Нет прогона → exit 1 и состояние ``missing`` (а не ``error``).

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(
        monkeypatch, {"lint.yml": _runs(_run("lint.yml", SHA)), "test.yml": _runs()}
    )
    clock = FakeClock()
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            SHA,
            "--workflows",
            "lint.yml",
            "test.yml",
            # Grace-период ожидания появления прогона отключён: тест про
            # состояние «прогона нет», а не про ожидание.
            "--missing-grace",
            "0",
        ],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "test.yml" in captured.out
    assert "missing" in captured.out
    assert "error" not in captured.out
    assert "test.yml: missing" in captured.err


# ── 4. Прогон ещё идёт — ждём завершения ───────────────────────────────


def test_in_progress_then_success_waits_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``in_progress`` → повторный опрос → ``success`` → exit 0 и ожидание было.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    responses = [
        _runs(_run("lint.yml", SHA, status="in_progress", conclusion=None)),
        _runs(_run("lint.yml", SHA, status="completed", conclusion="success")),
    ]

    def handler(url: str) -> subprocess.CompletedProcess[str]:
        assert "/actions/workflows/lint.yml/runs" in url
        return _ok(responses.pop(0))

    fake = FakeGh(handler)
    fake.install(monkeypatch)
    clock = FakeClock()
    code = gate.main(
        ["--repo", REPO, "--sha", SHA, "--workflows", "lint.yml"],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert clock.sleeps, "ожидание не выполнялось — гейт не ждал завершения прогона"
    assert len(fake.urls) == 2, "ожидался ровно один повторный опрос"


# ── 5. Дедлайн ожидания истёк ──────────────────────────────────────────


def test_in_progress_until_deadline_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Прогон не завершился до дедлайна → exit 1 с внятным сообщением.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(
        monkeypatch,
        {
            "lint.yml": _runs(
                _run("lint.yml", SHA, status="in_progress", conclusion=None)
            )
        },
    )
    clock = FakeClock()
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            SHA,
            "--workflows",
            "lint.yml",
            "--timeout",
            "3",
            "--interval",
            "1",
        ],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "НЕ ДОЖДАЛИСЬ" in captured.err
    assert "lint.yml" in captured.err
    assert "RELEASE GATE PASS" not in captured.out


# ── 6. Ошибка API — не «missing» ───────────────────────────────────────


@pytest.mark.parametrize(
    "response",
    [
        _api_error("gh: HTTP 403: Forbidden"),
        _api_error("gh: HTTP 500: Internal Server Error"),
        subprocess.CompletedProcess(
            args=["gh"], returncode=0, stdout="<not json>", stderr=""
        ),
    ],
    ids=["403", "500", "invalid-json"],
)
def test_api_error_exits_two_and_is_not_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response: subprocess.CompletedProcess[str],
) -> None:
    """Ошибка API → exit 2, состояние не ``missing``.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
        response: Ответ ``gh api`` с ошибкой.
    """
    _install(monkeypatch, {"lint.yml": response})
    code = gate.main(["--repo", REPO, "--sha", SHA, "--workflows", "lint.yml"])
    captured = capsys.readouterr()
    assert code == 2, captured.out + captured.err
    assert "missing" not in captured.out
    assert "error" in captured.out
    assert "ОШИБКА API" in captured.err


# ── 7. Чужой SHA игнорируется ──────────────────────────────────────────


def test_run_with_other_sha_is_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Прогон другого SHA не принимается → ``missing``.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(monkeypatch, {"lint.yml": _runs(_run("lint.yml", OTHER_SHA, run_id=7))})
    clock = FakeClock()
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            SHA,
            "--workflows",
            "lint.yml",
            "--missing-grace",
            "0",
        ],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "missing" in captured.out
    assert "run=7" not in captured.out


# ── 8. Несколько попыток прогона ───────────────────────────────────────


def test_latest_attempt_is_used(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Берётся актуальная попытка (``run_attempt`` > 1), а не первая.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(
        monkeypatch,
        {
            "lint.yml": _runs(
                _run("lint.yml", SHA, conclusion="failure", run_id=10, attempt=1),
                _run("lint.yml", SHA, conclusion="success", run_id=11, attempt=2),
            )
        },
    )
    code = gate.main(["--repo", REPO, "--sha", SHA, "--workflows", "lint.yml"])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "run=11" in captured.out


# ── 9. Используется workflow-specific endpoint ─────────────────────────


def test_uses_workflow_specific_endpoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Запрос идёт к ``/actions/workflows/<file>/runs``, а не к ``/actions/runs``.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    fake = _install(
        monkeypatch,
        {
            "lint.yml": _runs(_run("lint.yml", SHA)),
            "test.yml": _runs(_run("test.yml", SHA, run_id=2)),
        },
    )
    gate.main(["--repo", REPO, "--sha", SHA, "--workflows", "lint.yml", "test.yml"])
    capsys.readouterr()
    assert fake.urls
    for url in fake.urls:
        assert "/actions/workflows/" in url, url
        assert "/actions/runs?" not in url, url
        assert f"head_sha={SHA}" in url, url
    assert any("/actions/workflows/lint.yml/runs" in url for url in fake.urls)
    assert any("/actions/workflows/test.yml/runs" in url for url in fake.urls)


# ── 10. Прогон чужого workflow-файла ──────────────────────────────────


def test_run_of_foreign_workflow_path_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Прогон с чужим путём workflow-файла не принимается → ``missing``.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(
        monkeypatch,
        {
            "lint.yml": _runs(
                _run("lint.yml", SHA, run_id=9, path=".github/workflows/perf.yml")
            )
        },
    )
    clock = FakeClock()
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            SHA,
            "--workflows",
            "lint.yml",
            "--missing-grace",
            "0",
        ],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "missing" in captured.out
    assert "run=9" not in captured.out


# ── 11. Гонка запуска: прогон ещё не создан ────────────────────────────


def test_missing_run_appears_during_grace_waits_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Прогон, ещё не созданный на первом опросе, дожидается появления.

    Гейт стартует параллельно с upstream-workflow, поэтому на первом опросе
    их прогоны могут ещё не существовать. Если хотя бы один workflow по
    этому SHA уже стартовал, отсутствующий прогон не считается «нет
    прогона», а ждёт появления в пределах grace-периода.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    test_polls = {"count": 0}

    def handler(url: str) -> subprocess.CompletedProcess[str]:
        if "/actions/workflows/test.yml/runs" in url:
            test_polls["count"] += 1
            if test_polls["count"] == 1:
                # Первый опрос test.yml — прогона ещё нет.
                return _ok(_runs())
            return _ok(_runs(_run("test.yml", SHA, run_id=2)))
        return _ok(_runs(_run("lint.yml", SHA, run_id=1)))

    fake = FakeGh(handler)
    fake.install(monkeypatch)
    clock = FakeClock()
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            SHA,
            "--workflows",
            "lint.yml",
            "test.yml",
            "--missing-grace",
            "120",
        ],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert clock.sleeps, "ожидание не выполнялось — гонка запуска не обработана"


def test_missing_grace_expired_exits_one_with_missing_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Прогон так и не появился → после grace-периода ``missing`` и exit 1.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    _install(
        monkeypatch, {"lint.yml": _runs(_run("lint.yml", SHA)), "test.yml": _runs()}
    )
    clock = FakeClock()
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            SHA,
            "--workflows",
            "lint.yml",
            "test.yml",
            "--missing-grace",
            "60",
            "--interval",
            "30",
        ],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "test.yml: missing" in captured.err


def test_no_workflow_started_waits_grace_then_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ни один workflow не стартовал → ждём grace и только затем падаем.

    Гейт стартует параллельно с upstream-workflow, поэтому на первом опросе
    прогонов ещё нет — ранний выход делал бы гейт структурно красным
    (независимое ревью 2026-11-23, MINOR-9).

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    fake = _install(monkeypatch, {"lint.yml": _runs(), "test.yml": _runs()})
    clock = FakeClock()
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            SHA,
            "--workflows",
            "lint.yml",
            "test.yml",
            "--missing-grace",
            "60",
            "--interval",
            "30",
        ],
        sleep_fn=clock.sleep,
        clock=clock,
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert clock.sleeps, "гейт не дождался появления прогонов"
    assert "missing" in captured.out
    assert len(fake.urls) >= 4, "ожидались повторные опросы"


def test_multiple_acceptable_shas(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Несколько допустимых SHA (merge_group): прогон по любому из них принят.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    other_sha = "f" * 40
    _install(monkeypatch, {"lint.yml": _runs(_run("lint.yml", other_sha, run_id=5))})
    code = gate.main(
        ["--repo", REPO, "--sha", f"{SHA},{other_sha}", "--workflows", "lint.yml"]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "success" in captured.out


def test_foreign_sha_is_still_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Прогон по чужому SHA не принимается, даже если список SHA задан.

    Args:
        monkeypatch: Фикстура pytest.
        capsys: Захват вывода.
    """
    foreign_sha = "c" * 40
    _install(monkeypatch, {"lint.yml": _runs(_run("lint.yml", foreign_sha, run_id=6))})
    code = gate.main(
        [
            "--repo",
            REPO,
            "--sha",
            f"{SHA},{'b' * 40}",
            "--workflows",
            "lint.yml",
            "--missing-grace",
            "0",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + captured.err
    assert "missing" in captured.out
    assert foreign_sha not in captured.out
