#!/usr/bin/env python3
"""Release evidence manifest — машинно-читаемый отчёт о готовности.

Зачем
-----
Аудит prod-readiness (2026-11-20) требует заменить ручной «процент
готовности» машинным manifest'ом: правка отчёта на глаз не является
доказательством, а «всё зелёное» без привязки к коммиту, образу и профилю
нельзя проверить.

Этот инструмент собирает такой manifest:

* ``sha`` — коммит, на котором выполнялись проверки (+ признак грязного
  рабочего дерева: некоммиченные правки не имеют воспроизводимого
  артефакта);
* ``image_digest`` — digest образа (из аргумента, переменной окружения
  или ``docker image inspect``), иначе явный ``n/a``;
* ``profile`` — профиль развёртывания;
* ``commands`` — выполненные проверки: команда, exit code, длительность;
* ``test_scope`` — что именно проверялось;
* ``artifacts`` — файлы артефактов с sha256 и размером;
* ``external_blockers`` — внешние блокеры с указанием причины;
* ``verdict`` — ``READY_RC`` либо ``BLOCKED`` с причинами.

Вердикт вычисляется строго: ``READY_RC`` возможен только если выполнен
хотя бы один проверочный command, все команды завершились с кодом 0 и
внешних блокеров нет. Отсутствие доказательств — это блокер, а не успех.

Логи команд пишутся отдельными файлами (``<out_dir>/logs/<label>.log``), а
в manifest попадает только их sha256: секреты из вывода команд не должны
попадать в отчёт о готовности.

Запуск::

    python tools/checks/release_evidence.py \\
        --profile dev \\
        --scope "unit:tests/unit/entrypoints" \\
        --command "http-contract-smoke:python tools/checks/http_contract_smoke.py" \\
        --artifact coverage.xml \\
        --blocker "skb-stand:нет доступа к стенду СКБ" \\
        --out artifacts/release/evidence.json

Код возврата: 0 — manifest собран (READY_RC или BLOCKED зафиксированы в
самом manifest'е), 2 — ошибка конфигурации/окружения.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

#: Куда по умолчанию пишется manifest.
DEFAULT_OUT = Path("artifacts/release/evidence.json")
#: Сколько байт лога команды сохранять в manifest (только sha256 и размер).
MAX_LOG_TAIL = 200_000

VERDICT_READY = "READY_RC"
VERDICT_BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Результат одной выполненной проверки.

    Attributes:
        label: Имя проверки.
        command: Выполненная команда.
        exit_code: Код возврата.
        duration_s: Длительность, секунды.
        log_path: Путь к файлу лога (если логирование включено).
        log_sha256: Контрольная сумма лога.
    """

    label: str
    command: str
    exit_code: int
    duration_s: float
    log_path: str | None = None
    log_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    """Артефакт проверки.

    Attributes:
        path: Путь к файлу.
        sha256: Контрольная сумма.
        bytes: Размер, байт.
    """

    path: str
    sha256: str
    bytes: int


@dataclass
class EvidenceManifest:
    """Машинно-читаемый manifest о готовности.

    Attributes:
        schema_version: Версия схемы manifest'а.
        generated_at: Время формирования (UTC, ISO 8601).
        sha: Полный SHA коммита.
        sha_short: Короткий SHA.
        dirty: True — в рабочем дереве есть незакоммиченные правки.
        dirty_files: Количество изменённых файлов.
        image_digest: Digest образа либо ``n/a``.
        profile: Профиль развёртывания.
        python_version: Версия интерпретатора.
        platform: Платформа.
        test_scope: Что проверялось.
        commands: Результаты выполненных проверок.
        artifacts: Артефакты с контрольными суммами.
        external_blockers: Внешние блокеры.
        verdict: ``READY_RC`` либо ``BLOCKED``.
        verdict_reasons: Почему такой вердикт.
    """

    schema_version: int = 1
    generated_at: str = ""
    sha: str = ""
    sha_short: str = ""
    dirty: bool = False
    dirty_files: int = 0
    image_digest: str = "n/a"
    profile: str = "n/a"
    python_version: str = ""
    platform: str = ""
    test_scope: list[str] = field(default_factory=list)
    commands: list[CommandResult] = field(default_factory=list)
    artifacts: list[ArtifactResult] = field(default_factory=list)
    external_blockers: list[dict[str, str]] = field(default_factory=list)
    verdict: str = VERDICT_BLOCKED
    verdict_reasons: list[str] = field(default_factory=list)


def _run_git(args: list[str], cwd: Path) -> str | None:
    """Выполнить git-команду и вернуть stdout.

    Args:
        args: Аргументы git.
        cwd: Рабочий каталог.

    Returns:
        stdout без хвостовых пробелов либо ``None`` при ошибке.
    """
    cmd = ["git", *args]
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированная команда git
            cmd, capture_output=True, text=True, check=False, cwd=cwd, timeout=30
        )
    except OSError, subprocess.SubprocessError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _sha256_file(path: Path) -> tuple[str, int] | None:
    """Посчитать sha256 и размер файла.

    Args:
        path: Путь к файлу.

    Returns:
        Кортеж ``(sha256, размер)`` либо ``None``, если файла нет.
    """
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _resolve_image_digest(explicit: str | None, image: str | None) -> str:
    """Определить digest образа.

    Args:
        explicit: Явно переданный digest.
        image: Имя образа для ``docker image inspect``.

    Returns:
        Digest либо ``"n/a"``.
    """
    if explicit:
        return explicit
    env_digest = os.environ.get("IMAGE_DIGEST")
    if env_digest:
        return env_digest
    if not image:
        return "n/a"
    cmd = ["docker", "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"]
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированная команда docker
            cmd, capture_output=True, text=True, check=False, timeout=60
        )
    except OSError, subprocess.SubprocessError:
        return "n/a"
    if proc.returncode != 0:
        return "n/a"
    return proc.stdout.strip() or "n/a"


def _parse_pair(raw: str, separator: str, what: str) -> tuple[str, str]:
    """Разобрать аргумент вида ``имя:значение``.

    Args:
        raw: Исходная строка.
        separator: Разделитель.
        what: Что разбираем (для сообщения об ошибке).

    Returns:
        Кортеж ``(имя, значение)``.

    Raises:
        ValueError: Разделитель не найден.
    """
    name, _, value = raw.partition(separator)
    if not name or not value:
        raise ValueError(
            f"неверный формат {what}: {raw!r} (ожидается 'имя{separator}значение')"
        )
    return name.strip(), value.strip()


def _normalize_command(command: str) -> str:
    """Подставить интерпретатор текущего процесса вместо абстрактного ``python``.

    Код проекта форматируется ruff под ``target-version = py314`` и местами
    использует синтаксис PEP 758 (``except A, B:``) — такой файл не
    парсится системным Python 3.12. Если команда проверки начинается с
    ``python``/``python3``, она выполняется тем же интерпретатором, что и
    сам инструмент → поведение воспроизводимо и не зависит от PATH.

    Args:
        command: Команда как задана оператором.

    Returns:
        Команда с подставленным интерпретатором (при необходимости).
    """
    stripped = command.lstrip()
    if stripped.startswith(("python ", "python3 ")):
        return f"{sys.executable} {stripped[len('python') :].lstrip()}"
    return command


def _run_command(
    label: str, command: str, log_dir: Path | None, cwd: Path
) -> CommandResult:
    """Выполнить проверку и записать её лог.

    Args:
        label: Имя проверки.
        command: Команда для выполнения.
        log_dir: Каталог для логов (``None`` — без логирования).
        cwd: Рабочий каталог.

    Returns:
        Результат выполнения.
    """
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S602 — команда задана оператором запуска
            command,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            timeout=3600,
        )
        exit_code = proc.returncode
        output = f"{proc.stdout}\n{proc.stderr}"
    except subprocess.TimeoutExpired:
        exit_code = 124
        output = "таймаут выполнения команды (3600 с)"
    duration = round(time.monotonic() - started, 3)

    log_path: str | None = None
    log_sha: str | None = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{label}.log"
        path.write_text(output[-MAX_LOG_TAIL:], encoding="utf-8")
        computed = _sha256_file(path)
        if computed is not None:
            log_path = str(path)
            log_sha = computed[0]
    return CommandResult(
        label=label,
        command=command,
        exit_code=exit_code,
        duration_s=duration,
        log_path=log_path,
        log_sha256=log_sha,
    )


def collect_manifest(
    *,
    root: Path,
    profile: str,
    scopes: list[str],
    commands: list[tuple[str, str]],
    artifacts: list[str],
    blockers: list[tuple[str, str]],
    image: str | None,
    image_digest: str | None,
    log_dir: Path | None,
    run_commands: bool = True,
) -> EvidenceManifest:
    """Собрать manifest о готовности.

    Args:
        root: Корень репозитория.
        profile: Профиль развёртывания.
        scopes: Что проверялось (свободные формулировки).
        commands: Пары ``(имя, команда)``.
        artifacts: Пути к артефактам.
        blockers: Пары ``(имя, причина)``.
        image: Имя образа для определения digest.
        image_digest: Явно заданный digest.
        log_dir: Каталог для логов команд.
        run_commands: Выполнять команды (False — только зафиксировать,
            что проверки не выполнялись).

    Returns:
        Готовый manifest.
    """
    manifest = EvidenceManifest()
    manifest.generated_at = datetime.now(UTC).isoformat()
    manifest.profile = profile
    manifest.python_version = sys.version.split()[0]
    manifest.platform = sys.platform

    sha = _run_git(["rev-parse", "HEAD"], root)
    manifest.sha = sha or "n/a"
    manifest.sha_short = sha[:12] if sha else "n/a"
    status = _run_git(["status", "--porcelain"], root)
    if status is not None:
        changed = [line for line in status.splitlines() if line.strip()]
        manifest.dirty_files = len(changed)
        manifest.dirty = bool(changed)

    manifest.image_digest = _resolve_image_digest(image_digest, image)
    manifest.test_scope = list(scopes)

    for path in artifacts:
        computed = _sha256_file(Path(path))
        if computed is None:
            continue
        manifest.artifacts.append(
            ArtifactResult(path=path, sha256=computed[0], bytes=computed[1])
        )

    manifest.external_blockers = [
        {"name": name, "reason": reason} for name, reason in blockers
    ]

    if run_commands:
        for label, command in commands:
            manifest.commands.append(
                _run_command(label, _normalize_command(command), log_dir, root)
            )

    reasons: list[str] = []
    failed = [cmd for cmd in manifest.commands if cmd.exit_code != 0]
    if failed:
        reasons.append(
            "проверки завершились с ненулевым кодом: "
            + ", ".join(f"{cmd.label}={cmd.exit_code}" for cmd in failed)
        )
    if not manifest.commands:
        reasons.append("ни одна проверка не выполнена — доказательств нет")
    if not manifest.test_scope:
        reasons.append(
            "не указан test_scope — неясно, что именно проверено, "
            "зелёный вердикт без объёма проверок читается как «всё хорошо»"
        )
    if manifest.dirty:
        reasons.append(
            f"рабочее дерево не чистое ({manifest.dirty_files} файлов) — "
            "артефакт невоспроизводим по SHA"
        )
    if manifest.external_blockers:
        reasons.append(
            "внешние блокеры: "
            + ", ".join(block["name"] for block in manifest.external_blockers)
        )
    manifest.verdict_reasons = reasons
    manifest.verdict = VERDICT_READY if not reasons else VERDICT_BLOCKED
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы командной строки (по умолчанию ``sys.argv[1:]``).

    Returns:
        0 — manifest собран; 2 — ошибка конфигурации.
    """
    parser = argparse.ArgumentParser(
        description="Машинно-читаемый manifest о готовности к релизу"
    )
    parser.add_argument("--root", default=".", help="Корень репозитория")
    parser.add_argument(
        "--profile",
        default=os.environ.get("DEPLOYMENT_PROFILE", "n/a"),
        help="Профиль развёртывания (по умолчанию env DEPLOYMENT_PROFILE)",
    )
    parser.add_argument(
        "--scope",
        action="append",
        default=[],
        help=(
            "Что проверялось (можно указать несколько раз). Обязателен: "
            "без объёма проверок вердикт нечитаем"
        ),
    )
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        metavar="ИМЯ:КОМАНДА",
        help="Проверка к выполнению (метка:команда); можно указать несколько раз",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        help="Артефакт для фиксации (путь к файлу)",
    )
    parser.add_argument(
        "--blocker",
        action="append",
        default=[],
        metavar="ИМЯ:ПРИЧИНА",
        help="Внешний блокер (имя:причина)",
    )
    parser.add_argument("--image", default=None, help="Имя образа для digest")
    parser.add_argument("--image-digest", default=None, help="Явный digest образа")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"Путь к manifest'у (по умолчанию {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Не выполнять команды — только зафиксировать их состав",
    )
    parser.add_argument(
        "--no-logs",
        action="store_true",
        help="Не сохранять логи команд (в manifest попадут только коды)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ОШИБКА: корня репозитория нет: {root}", file=sys.stderr)
        return 2

    try:
        commands = [_parse_pair(raw, ":", "проверки") for raw in args.command]
        blockers = [_parse_pair(raw, ":", "блокера") for raw in args.blocker]
    except ValueError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    log_dir = None if args.no_logs else out_path.parent / "logs"

    manifest = collect_manifest(
        root=root,
        profile=args.profile,
        scopes=list(args.scope),
        commands=commands,
        artifacts=list(args.artifact),
        blockers=blockers,
        image=args.image,
        image_digest=args.image_digest,
        log_dir=log_dir,
        run_commands=not args.no_run,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Manifest: {out_path}")
    print(
        f"  sha:            {manifest.sha}{' (грязное дерево)' if manifest.dirty else ''}"
    )
    print(f"  profile:        {manifest.profile}")
    print(f"  image_digest:   {manifest.image_digest}")
    print(f"  проверки:       {len(manifest.commands)}")
    print(f"  артефакты:      {len(manifest.artifacts)}")
    print(f"  блокеры:        {len(manifest.external_blockers)}")
    print(f"  вердикт:        {manifest.verdict}")
    for reason in manifest.verdict_reasons:
        print(f"    - {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
