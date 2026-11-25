"""Регрессионные тесты контракта mutation-гейта (ADR-0452).

Покрывают:

1. Чтение порога из ``.baselines/mutation.json`` (без молчаливого fallback'а).
2. Exit-коды гейта: PASS / FAIL / SKIPPED / ERROR.
3. Защиту от «прогона вхолостую»: устаревшая статистика не переиспользуется,
   отсутствие mutmut/данных даёт SKIPPED с явной причиной, а не PASS.
4. Сохранение кэша результатов мутаций (``mutants/*.meta``) при синхронизации
   рабочей копии — без этого каждый прогон стартует с нуля (часы вместо минут).
5. CI-обвязку: у шага mutation-гейта есть таймаут и разбор exit-кодов.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tools.checks import check_mutmut, run_mutmut

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_FILE = REPO_ROOT / ".baselines" / "mutation.json"
LINT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lint.yml"


def _write_stats(path: Path, *, killed: int, total: int) -> Path:
    """Записать файл статистики mutmut с заданными значениями."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "killed": killed,
                "survived": max(total - killed, 0),
                "total": total,
                "no_tests": 0,
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def gate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Подготовить окружение для вызова ``check_mutmut.main()``.

    Отключает тяжёлые side-effect'ы (rsync рабочей копии мутантов, патч
    установленного mutmut) и подменяет прогон/экспорт мутаций.
    """
    calls: dict[str, object] = {"stats": tmp_path / "mutmut-cicd-stats.json"}

    monkeypatch.setattr(check_mutmut, "_patch_mutmut", lambda: None)
    monkeypatch.setattr(check_mutmut, "_sync_mutants_src", lambda: None)
    monkeypatch.setattr(check_mutmut, "_sync_mutants_assets", lambda: None)
    monkeypatch.setattr(check_mutmut, "_mutmut_available", lambda: True)
    monkeypatch.setattr(check_mutmut, "_run_mutmut", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        check_mutmut, "_export_cicd_stats", lambda *_args, **_kwargs: calls["stats"]
    )
    return calls


class TestBaselineReading:
    """Порог гейта берётся из baseline-файла, а не из константы в коде."""

    def test_baseline_path_is_repo_root_relative(self) -> None:
        """Путь к baseline не зависит от текущего рабочего каталога."""
        assert check_mutmut.BASELINE_PATH == BASELINE_FILE
        assert check_mutmut.BASELINE_PATH.is_absolute()
        assert check_mutmut.BASELINE_PATH.exists()

    def test_reads_threshold_from_baseline(self) -> None:
        """Значение порога читается из .baselines/mutation.json."""
        expected = float(
            json.loads(BASELINE_FILE.read_text(encoding="utf-8"))[
                "mutation_score_percent"
            ]
        )
        assert check_mutmut._load_baseline() == expected

    def test_missing_baseline_raises(self, tmp_path: Path) -> None:
        """Отсутствие baseline — ошибка конфигурации, а не молчаливый fallback."""
        with pytest.raises(check_mutmut.BaselineError):
            check_mutmut._load_baseline(tmp_path / "нет-такого.json")

    def test_corrupt_baseline_raises(self, tmp_path: Path) -> None:
        """Битый JSON baseline — ошибка конфигурации."""
        broken = tmp_path / "mutation.json"
        broken.write_text("{not json", encoding="utf-8")
        with pytest.raises(check_mutmut.BaselineError):
            check_mutmut._load_baseline(broken)

    def test_non_numeric_threshold_raises(self, tmp_path: Path) -> None:
        """Нечисловой порог в baseline — ошибка конфигурации."""
        bad = tmp_path / "mutation.json"
        bad.write_text(json.dumps({"mutation_score_percent": "high"}), encoding="utf-8")
        with pytest.raises(check_mutmut.BaselineError):
            check_mutmut._load_baseline(bad)

    def test_missing_key_raises(self, tmp_path: Path) -> None:
        """Baseline без ключа mutation_score_percent — ошибка конфигурации."""
        bad = tmp_path / "mutation.json"
        bad.write_text(json.dumps({"other": 1}), encoding="utf-8")
        with pytest.raises(check_mutmut.BaselineError):
            check_mutmut._load_baseline(bad)


class TestScoreParsing:
    """Score = killed / total (метрика baseline'а)."""

    def test_score_is_killed_over_total(self, tmp_path: Path) -> None:
        """Score считается как доля убитых мутаций."""
        stats = _write_stats(tmp_path / "s.json", killed=247, total=1142)
        assert check_mutmut._parse_score(stats) == pytest.approx(21.6, abs=0.05)

    def test_zero_total_has_no_score(self, tmp_path: Path) -> None:
        """Ноль мутаций — измерять нечего (None, а не 0.0)."""
        stats = _write_stats(tmp_path / "s.json", killed=0, total=0)
        assert check_mutmut._parse_score(stats) is None


class TestExitCodes:
    """Контракт exit-кодов: 0=PASS, 1=FAIL, 2=SKIPPED, 3=ERROR."""

    def test_pass_when_score_reaches_threshold(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Score на уровне порога — PASS (exit 0)."""
        stats = _write_stats(Path(gate_env["stats"]), killed=30, total=100)  # type: ignore[arg-type]
        monkeypatch.setattr(check_mutmut, "_export_cicd_stats", lambda *_a, **_k: stats)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py", "--threshold", "30"])
        assert check_mutmut.main() == check_mutmut.EXIT_PASS

    def test_fail_when_score_below_threshold(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Score ниже порога — FAIL (exit 1)."""
        stats = _write_stats(Path(gate_env["stats"]), killed=10, total=100)  # type: ignore[arg-type]
        monkeypatch.setattr(check_mutmut, "_export_cicd_stats", lambda *_a, **_k: stats)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py", "--threshold", "50"])
        assert check_mutmut.main() == check_mutmut.EXIT_FAIL

    def test_threshold_defaults_to_baseline(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Без --threshold порог берётся из baseline (рэтчет «не хуже baseline»)."""
        baseline = check_mutmut._load_baseline()
        # score ровно на уровне baseline — PASS (значение baseline берётся из
        # файла, а не из константы в тесте: baseline рэтчится по мере роста
        # покрытия, и зашитый литерал ломался на каждом обновлении).
        total = 1000
        killed = round(baseline * total / 100)
        stats = _write_stats(Path(gate_env["stats"]), killed=killed, total=total)  # type: ignore[arg-type]
        monkeypatch.setattr(check_mutmut, "_export_cicd_stats", lambda *_a, **_k: stats)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py"])
        assert check_mutmut.main() == check_mutmut.EXIT_PASS
        # Baseline обязан оставаться в разумном диапазоне (защита от
        # ошибочного значения в .baselines/mutation.json).
        assert 15.0 <= baseline <= 30.0

    def test_skipped_when_no_mutation_data(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Нет данных о мутациях — SKIPPED (exit 2), а не PASS."""

        def _raise(*_args: object, **_kwargs: object) -> Path:
            raise check_mutmut.NoMutationData("нет данных о мутациях")

        monkeypatch.setattr(check_mutmut, "_export_cicd_stats", _raise)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py"])
        assert check_mutmut.main() == check_mutmut.EXIT_SKIPPED

    def test_skipped_when_all_mutants_have_no_tests(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Если ни один мутант не покрыт тестами — SKIPPED, а не «score 0.0 %».

        Score 0.0 % при полном отсутствии тестов — артефакт пустой карты
        тест↔мутант, а не измеренная регрессия.
        """
        stats_path = Path(gate_env["stats"])  # type: ignore[arg-type]
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.write_text(
            json.dumps({"killed": 0, "survived": 0, "total": 78, "no_tests": 78}),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            check_mutmut, "_export_cicd_stats", lambda *_a, **_k: stats_path
        )
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py"])
        assert check_mutmut.main() == check_mutmut.EXIT_SKIPPED

    def test_skipped_when_mutmut_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Нет mutmut в интерпретаторе — SKIPPED (exit 2), а не PASS."""
        monkeypatch.setattr(check_mutmut, "_mutmut_available", lambda: False)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py"])
        assert check_mutmut.main() == check_mutmut.EXIT_SKIPPED

    def test_skipped_when_time_budget_exhausted(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Исчерпанный бюджет времени — SKIPPED (exit 2), а не PASS."""

        def _timeout(*_args: object, **_kwargs: object) -> int:
            raise check_mutmut.TimeBudgetExceeded("превышен бюджет времени")

        monkeypatch.setattr(check_mutmut, "_run_mutmut", _timeout)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py", "--timeout", "1"])
        assert check_mutmut.main() == check_mutmut.EXIT_SKIPPED

    def test_error_when_baseline_broken(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Нечитаемый baseline — ERROR (exit 3), а не PASS/FAIL."""

        def _raise(*_args: object, **_kwargs: object) -> float:
            raise check_mutmut.BaselineError("baseline-файл не найден")

        monkeypatch.setattr(check_mutmut, "_load_baseline", _raise)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py"])
        assert check_mutmut.main() == check_mutmut.EXIT_ERROR

    def test_fail_when_mutation_run_failed(
        self, monkeypatch: pytest.MonkeyPatch, gate_env: dict[str, object]
    ) -> None:
        """Упавший прогон мутаций — FAIL (exit 1), а не SKIPPED."""
        monkeypatch.setattr(check_mutmut, "_run_mutmut", lambda *_a, **_k: 1)
        monkeypatch.setattr(sys, "argv", ["check_mutmut.py"])
        assert check_mutmut.main() == check_mutmut.EXIT_FAIL


class TestStaleStatsNotReused:
    """Устаревшая статистика не должна выдаваться за текущий score."""

    def test_stale_stats_removed_before_export(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Старый stats-файл удаляется до экспорта: без этого гейт сравнил бы
        со score ПРОШЛОГО прогона (mutmut export-cicd-stats при отсутствии
        данных не перезаписывает файл и выходит с кодом 0)."""
        stats = tmp_path / "mutants" / "mutmut-cicd-stats.json"
        _write_stats(stats, killed=999, total=1000)
        assert stats.exists()

        monkeypatch.setattr(check_mutmut, "subprocess", subprocess)
        monkeypatch.setattr(
            check_mutmut.subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0),
        )
        with pytest.raises(check_mutmut.NoMutationData):
            check_mutmut._export_cicd_stats(tmp_path, {})
        assert not stats.exists(), "устаревшая статистика не должна оставаться"


class TestPartialRunNotMeasured:
    """Прерванный прогон не должен выдаваться за измеренный score."""

    def test_not_checked_count_reads_meta_verdicts(self, tmp_path: Path) -> None:
        """Мутанты без вердикта (None) считаются непроверенными."""
        meta = tmp_path / "mutants" / "src" / "mod.py.meta"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            json.dumps({"exit_code_by_key": {"a": 1, "b": None, "c": None, "d": 33}}),
            encoding="utf-8",
        )
        assert check_mutmut._not_checked_count(tmp_path, ["src/mod.py"]) == 2

    def test_complete_meta_has_no_not_checked(self, tmp_path: Path) -> None:
        """Завершённый прогон: у всех мутантов есть вердикт."""
        meta = tmp_path / "mutants" / "src" / "mod.py.meta"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            json.dumps({"exit_code_by_key": {"a": 1, "b": 0, "c": 33}}),
            encoding="utf-8",
        )
        assert check_mutmut._not_checked_count(tmp_path, ["src/mod.py"]) == 0

    def test_source_paths_read_from_pyproject(self) -> None:
        """Набор мутируемых модулей берётся из [tool.mutmut] pyproject.toml."""
        paths = check_mutmut._mutated_source_paths(REPO_ROOT)
        assert "src/backend/core/resilience/breaker.py" in paths
        assert len(paths) == 10


class TestMutmutCachePreserved:
    """Кэш результатов мутаций (mutants/*.meta) нельзя стирать синхронизацией."""

    def test_sync_excludes_meta_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """rsync мутируемых исходников исключает *.meta из --delete."""
        captured: list[list[str]] = []

        def _fake_run(
            cmd: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[bytes]:
            captured.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(run_mutmut.subprocess, "run", _fake_run)
        run_mutmut._sync_mutants_src()

        assert captured, "rsync не вызывался"
        rsync_cmd = next(cmd for cmd in captured if cmd and cmd[0] == "rsync")
        assert "--delete" in rsync_cmd
        assert "--exclude=*.meta" in rsync_cmd


class TestCiWiring:
    """CI-обвязка mutation-гейта в lint.yml.

    Волна 35: гейт вынесен из перегруженного job'а ``lint`` (15 мин на ~35
    шагов) в отдельный job ``mutation`` (45 мин) с кэшем ``mutants/`` —
    иначе прогон не укладывался в бюджет и гейт всегда давал SKIPPED.
    """

    @staticmethod
    def _mutation_job() -> dict[str, object]:
        workflow = yaml.safe_load(LINT_WORKFLOW.read_text(encoding="utf-8"))
        jobs = workflow["jobs"]
        assert "mutation" in jobs, "job mutation не найден в lint.yml"
        return jobs["mutation"]

    @staticmethod
    def _mutation_step() -> dict[str, object]:
        steps = TestCiWiring._mutation_job()["steps"]
        matches = [s for s in steps if "check_mutmut.py" in str(s.get("run", ""))]
        assert matches, "шаг mutation-гейта не найден в job'е mutation"
        return matches[0]

    def test_step_has_timeout(self) -> None:
        """У job'а и у шага есть собственные таймауты."""
        job = self._mutation_job()
        assert "timeout-minutes" in job
        assert "timeout-minutes" in self._mutation_step()

    def test_step_maps_exit_codes(self) -> None:
        """Шаг разбирает exit-коды гейта: FAIL блокирует, SKIPPED — warning."""
        run_block = str(self._mutation_step()["run"])
        assert "check_mutmut.py" in run_block
        for code in ("0", "1", "2"):
            assert f"{code})" in run_block, f"нет ветки для exit-кода {code}"

    def test_step_uses_project_interpreter(self) -> None:
        """Шаг запускается через uv run (venv проекта, Python 3.14)."""
        assert "uv run python" in str(self._mutation_step()["run"])

    def test_job_caches_mutants_workspace(self) -> None:
        """Job кэширует рабочую копию mutants/ — прогон инкрементальный."""
        steps = self._mutation_job()["steps"]
        cache_steps = [s for s in steps if "actions/cache" in str(s.get("uses", ""))]
        assert cache_steps, "в job'е mutation нет кэша mutants/"
        assert "mutants" in str(cache_steps[0].get("with", {}).get("path", ""))
