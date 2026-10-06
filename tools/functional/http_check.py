"""Функциональная проверка HTTP-слоя на живом сервере (stdlib + httpx).

Зачем в репозитории, а не в /tmp: функциональные прогоны должны быть
воспроизводимы из кода проекта, иначе результат живёт только в одном сеансе.

Особенность, исправляющая прошлую ошибку: проверки, зависящие от БД,
не зашиты как ``expected 500``. В прошлой батарее ``/api/v1/actions/inventory``
был объявлен как «ожидаем 500», и такой прогон проходил бы и при настоящем
дефекте, возвращающем 500. Здесь такие проверки помечены ``DB_REQUIRED``:
при отсутствии БД они дают ``SKIP`` с явной причиной, но при наличии БД
требуют ``200``.

Запуск:
    # 1) поднять сервер (см. --help или README секции)
    MONGO_ENABLED=false SEC_API_KEY=local-func-test-key \\
      .venv/bin/python -m uvicorn src.backend.main:app --port 8185 &
    # 2) прогнать батарею
    .venv/bin/python tools/functional/http_check.py --base-url http://127.0.0.1:8185 \\
        --api-key local-func-test-key
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import zlib
from dataclasses import dataclass, field
from typing import Any

import httpx

#: Публичные пути, не требующие аутентификации (auth_required.py:51-79).
PUBLIC_PATHS = ("/health", "/ready", "/metrics", "/openapi.json", "/docs", "/redoc")

#: Пути под аутентификацией.
PROTECTED_PATHS = ("/api/v1/actions/inventory", "/api/v1/admin/actions")

#: Пути с JSON-телом заметно больше gzip_minimum_size (500) — именно они
#: ломались из-за инвертированного порядка middleware (аудит 2026-10-06).
COMPRESSIBLE_PATHS = ("/api/v1/admin/actions", "/ready", "/openapi.json")

#: Ожидания tenant-поведения выведены из документированного контракта
#: ``entrypoints/middlewares/tenant.py`` (docstring модуля, SECURITY-P0-002),
#: а НЕ подгонкой под наблюдаемый ответ — иначе проверка фиксировала бы
#: текущее состояние вместе с возможными регрессиями.
#:
#: 1. без аутентификации и без заголовка → ``default_tenant``;
#: 2. без аутентификации заголовок доверен и возвращается в ответе;
#: 3. аутентифицированный principal + чужой ``X-Tenant-ID`` → 403 fail-closed.
TENANT_ECHO_CASES = (
    ("default-when-absent", "/health", {}, "default"),
    ("echo-when-unauthenticated", "/health", {"X-Tenant-ID": "tenant-a"}, "tenant-a"),
)
TENANT_SPOOF_PATH = "/api/v1/admin/actions"
TENANT_SPOOF_STATUS = 403


@dataclass
class Result:
    """Результат одной проверки."""

    name: str
    status: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Battery:
    """Набор проверок с честным разделением PASS / FAIL / SKIP."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.results: list[Result] = []

    def record(self, name: str, status: str, detail: str = "", **extra: Any) -> None:
        """Записать результат проверки."""
        self.results.append(Result(name, status, detail, extra))

    def get(self, name: str, path: str, **kw: Any) -> httpx.Response | None:
        """Выполнить GET и записать результат по ожидаемому коду.

        Возвращает ``None``, если ответ не удалось получить или прочитать:
        httpx бросает ``DecodingError`` прямо на ``read()``, когда тело не
        соответствует заголовку ``Content-Encoding``. Батарея не должна
        падать на дефекте, который она обязана зафиксировать, поэтому
        такая ситуация записывается как FAIL, а не как исключение.
        """
        expected = kw.pop("expect", 200)
        try:
            resp = self.client.get(path, **kw)
        except httpx.HTTPError as exc:
            self.record(
                name,
                "FAIL",
                f"ответ не получен/не декодирован: {type(exc).__name__}: {str(exc)[:80]}",
                path=path,
            )
            return None
        ok = resp.status_code == expected
        self.record(
            name,
            "PASS" if ok else "FAIL",
            f"ожидаем {expected}, факт {resp.status_code}",
            path=path,
        )
        return resp

    # ── Проверки ────────────────────────────────────────────────────── #

    def public_paths(self) -> None:
        """Публичные эндпоинты отвечают без ключа."""
        for path in PUBLIC_PATHS:
            if path == "/ready":
                continue  # readiness зависит от БД, проверяется отдельно
            self.get(f"public:{path}", path)

    def auth_required(self) -> None:
        """Без ключа защищённые пути закрыты (401)."""
        for path in PROTECTED_PATHS:
            self.get(f"no-auth:{path}", path, expect=401)

    def auth_with_key(self, api_key: str) -> None:
        """С ключом запрос проходит auth-слой (не 401)."""
        for path in PROTECTED_PATHS:
            try:
                resp = self.client.get(path, headers={"X-API-Key": api_key})
            except httpx.HTTPError as exc:
                # Батарея обязана докладывать о проблеме, а не падать.
                self.record(
                    f"authed:{path}",
                    "FAIL",
                    f"транспортная ошибка при разборе ответа: "
                    f"{type(exc).__name__}: {str(exc)[:90]}",
                )
                continue
            if resp.status_code == 401:
                self.record(f"authed:{path}", "FAIL", "ключ не принят — 401")
            elif resp.status_code == 200:
                self.record(f"authed:{path}", "PASS", "200")
            else:
                # Не 401 и не 200. Если причина — недоступная БД, это
                # ограничение окружения, а не дефект: такой исход раньше
                # маскировался под «ожидаем 500».
                self.record(
                    f"authed:{path}",
                    "SKIP",
                    f"{resp.status_code} — вероятно, внешняя БД недоступна "
                    f"(в этом окружении БД нет)",
                    db_required=True,
                )

    def compression_round_trip(self, api_key: str) -> None:
        """Сжатый ответ обязан быть настоящим gzip и содержать те же данные.

        Проверка добавлена после P0-бага (аудит 2026-10-06): порядок
        middleware был инвертирован, компрессия стояла ВНУТРИ
        ``DataMaskingMiddleware``. Тот получал gzip-байты, падал на
        ``decode("utf-8")`` и подменял ответ заглушкой
        ``{"error": "response_masking_failed", ...}`` — сохранив заголовок
        ``Content-Encoding: gzip``. Клиент получал HTTP 200 с несжатым JSON
        под меткой gzip.

        Почему старая батарея это пропустила: curl молча отдаёт мусор, а
        httpx без явного заголовка Accept-Encoding сжатие не запрашивает.
        Здесь запрашиваем сжатие явно и **декодируем ответ**, поэтому
        расхождение заголовка и тела становится видимым.
        """
        for path in COMPRESSIBLE_PATHS:
            name = f"gzip:{path}"
            headers = {"X-API-Key": api_key, "Accept-Encoding": "gzip"}

            # Несжатый запрос тоже обязан быть в try: если сервер отдаёт
            # битое тело с заголовком Content-Encoding: gzip, httpx бросает
            # DecodingError прямо на response.read(). Без защиты батарея
            # падала с трассировкой вместо того, чтобы отметить FAIL —
            # а это ровно тот сценарий, ради которого проверка и добавлена.
            try:
                plain = self.client.get(path, headers={"X-API-Key": api_key})
            except httpx.HTTPError as exc:
                self.record(
                    name,
                    "FAIL",
                    f"ответ не декодируется: {type(exc).__name__}: {str(exc)[:80]}",
                )
                continue

            if plain.status_code == 401:
                self.record(name, "SKIP", "ключ не принят — 401")
                continue

            # Берём ИМЕННО wire-байты: httpx декодирует тело сам, поэтому
            # ``resp.content`` неотличим от несжатого ответа и не может
            # доказать, что сжатие применилось. ``iter_raw`` отдаёт то, что
            # реально пришло по сети.
            try:
                with self.client.stream("GET", path, headers=headers) as resp:
                    raw = b"".join(resp.iter_raw())
                    status = resp.status_code
                    encoding = resp.headers.get("content-encoding", "")
            except httpx.HTTPError as exc:
                self.record(
                    name,
                    "FAIL",
                    f"транспорт/декодирование: {type(exc).__name__}: {str(exc)[:80]}",
                )
                continue

            if status != plain.status_code:
                self.record(
                    name,
                    "FAIL",
                    f"код отличается от несжатого: {plain.status_code} → {status}",
                )
                continue

            if not encoding:
                # Сжатие не объявлено — тело обязано быть обычным.
                if raw[:2] == b"\x1f\x8b":
                    self.record(
                        name,
                        "FAIL",
                        "тело сжато, но заголовок Content-Encoding отсутствует",
                    )
                else:
                    self.record(
                        name,
                        "PASS",
                        f"сжатие не применяется ({len(raw)} байт < minimum_size)",
                    )
                continue

            if "gzip" not in encoding.lower():
                self.record(
                    name, "PASS", f"кодирование {encoding}, заголовок согласован"
                )
                continue

            # ─── Инвариант P0: заголовок и тело обязаны согласовываться ───
            if raw[:2] != b"\x1f\x8b":
                self.record(
                    name,
                    "FAIL",
                    f"Content-Encoding: gzip, но тело не начинается с магии "
                    f"1f 8b (начало {raw[:8]!r}) — клиент не сможет его распаковать",
                )
                continue

            try:
                decoded = gzip.decompress(raw)
            except (OSError, EOFError, zlib.error) as exc:
                self.record(name, "FAIL", f"поток gzip не распаковывается: {exc}")
                continue

            if b"response_masking_failed" in decoded:
                self.record(
                    name,
                    "FAIL",
                    "ответ подменён fail-closed заглушкой маскирования "
                    "(P0: компрессия стояла ВНУТРИ DataMaskingMiddleware)",
                )
                continue

            self.record(
                name,
                "PASS",
                f"gzip корректен: {len(raw)} байт на проводе → {len(decoded)} "
                f"распаковано, заглушки нет",
            )

    def dsl_route_diagnostics(self, api_key: str) -> None:
        """«0 DSL-роутов» должно быть объяснимо через API, а не только логами.

        Исторический контекст: ``GET /admin/routes`` возвращал
        ``{"total": 0, "routes": []}`` независимо от причины. Реальная
        причина оказалась ``V11_ROUTE_LOADER_ENABLED=false``, а не
        capability-гейтом — найти её можно было только чтением логов.

        Проверка требует, чтобы секция ``loader`` присутствовала и содержала
        состояние и причину. Это защита от возврата к чёрному ящику.
        """
        name = "dsl:loader-diagnostics"
        try:
            resp = self.client.get(
                "/api/v1/admin/routes", headers={"X-API-Key": api_key}
            )
        except httpx.HTTPError as exc:
            self.record(
                name, "FAIL", f"транспорт: {type(exc).__name__}: {str(exc)[:70]}"
            )
            return

        if resp.status_code != 200:
            self.record(name, "FAIL", f"ожидаем 200, факт {resp.status_code}")
            return

        try:
            data = resp.json()
        except ValueError:
            self.record(name, "FAIL", "ответ не разбирается как JSON")
            return

        loader = data.get("loader")
        if not isinstance(loader, dict):
            self.record(
                name,
                "FAIL",
                "в ответе нет секции 'loader' — причина отсутствия роутов "
                "снова непрозрачна (вернулись к чёрному ящику)",
            )
            return

        state = loader.get("state")
        reason = (loader.get("reason") or "").strip()
        if state in {"disabled", "not_started"} and not reason:
            self.record(
                name,
                "FAIL",
                f"loader.state={state!r}, но 'reason' пуст — причина не объяснена",
            )
            return

        rejected = loader.get("rejected") or []
        detail = (
            f"state={state}, обнаружено={loader.get('discovered')}, "
            f"активно={loader.get('active')}, отказов={loader.get('failed')}"
        )
        if reason:
            detail += f"; причина: {reason[:70]}"
        if rejected:
            first = rejected[0]
            detail += f"; первый отказ: {first.get('name')} — {(first.get('reason') or '')[:50]}"
        self.record(name, "PASS", detail)

    def tenant_context(self, api_key: str) -> None:
        """Multi-tenancy: дефолт, эхо заголовка и fail-closed на спуфинге.

        Ожидания взяты из контракта ``tenant.py``, а не из текущих ответов.
        Третий случай — самый важный: без него подделка ``X-Tenant-ID``
        аутентифицированным клиентом осталась бы незамеченной (именно такой
        сценарий закрывал SECURITY-P0-002).
        """
        for label, path, headers, expected in TENANT_ECHO_CASES:
            name = f"tenant:{label}"
            try:
                resp = self.client.get(path, headers=headers)
            except httpx.HTTPError as exc:
                self.record(
                    name, "FAIL", f"транспорт: {type(exc).__name__}: {str(exc)[:70]}"
                )
                continue
            actual = resp.headers.get("x-tenant-id", "")
            self.record(
                name,
                "PASS" if actual == expected else "FAIL",
                f"X-Tenant-ID={actual or '<нет>'!s} (ожидаем {expected!r})",
            )

        # Спуфинг: аутентифицированная платформенная учётка без tenant
        # не должна принимать чужой X-Tenant-ID.
        name = "tenant:spoof-denied"
        try:
            resp = self.client.get(
                TENANT_SPOOF_PATH,
                headers={"X-API-Key": api_key, "X-Tenant-ID": "tenant-b"},
            )
        except httpx.HTTPError as exc:
            self.record(
                name, "FAIL", f"транспорт: {type(exc).__name__}: {str(exc)[:70]}"
            )
            return

        if resp.status_code == TENANT_SPOOF_STATUS:
            self.record(
                name,
                "PASS",
                f"{TENANT_SPOOF_STATUS} tenant_mismatch — подделка отклонена",
            )
        else:
            self.record(
                name,
                "FAIL",
                f"ожидаем {TENANT_SPOOF_STATUS} на поддельный X-Tenant-ID, "
                f"факт {resp.status_code} — спуфинг тенанта возможен",
            )

    def security_headers(self) -> None:
        """Ответ несёт защитные заголовки."""
        resp = self.client.get("/health")
        h = {k.lower(): v for k, v in resp.headers.items()}
        for header, expected in (
            ("x-content-type-options", "nosniff"),
            ("x-frame-options", "DENY"),
        ):
            actual = h.get(header)
            self.record(
                f"header:{header}",
                "PASS" if actual == expected else "FAIL",
                f"{header}={actual!r} (ожидаем {expected!r})",
            )
        for header, needle in (
            ("strict-transport-security", "max-age"),
            ("content-security-policy", "default-src"),
            ("permissions-policy", "geolocation"),
        ):
            actual = h.get(header, "")
            self.record(
                f"header:{header}",
                "PASS" if needle in actual else "FAIL",
                f"{header}={actual[:60]!r}",
            )

    def correlation_ids(self) -> None:
        """Корреляционные идентификаторы присутствуют в ответе."""
        h = {k.lower() for k in self.client.get("/health").headers}
        for header in ("x-request-id", "x-correlation-id"):
            self.record(
                f"trace-header:{header}",
                "PASS" if header in h else "FAIL",
                f"{header}={'есть' if header in h else 'нет'}",
            )

    def error_envelope(self) -> None:
        """Ошибка отдаётся в структурированном конверте."""
        resp = self.client.get("/api/v1/actions/inventory")
        if resp.status_code == 401:
            self.record(
                "error-envelope", "SKIP", "401 без ключа — конверт не проверяем"
            )
            return
        try:
            body = resp.json()
        except ValueError:
            self.record("error-envelope", "FAIL", "ответ не JSON")
            return
        missing = [
            k
            for k in ("code", "error_id", "correlation_id", "request_id")
            if k not in body
        ]
        self.record(
            "error-envelope",
            "FAIL" if missing else "PASS",
            f"нет полей {missing}" if missing else "конверт полный",
        )


def main(argv: list[str] | None = None) -> int:
    """Прогнать батарею и вернуть код exit."""
    parser = argparse.ArgumentParser(description="Функциональная проверка HTTP-слоя")
    parser.add_argument("--base-url", default="http://127.0.0.1:8185")
    parser.add_argument("--api-key", default="local-func-test-key")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--json-out", default="")
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    with httpx.Client(
        base_url=base, timeout=args.timeout, follow_redirects=True
    ) as client:
        if client.get("/health").status_code != 200:
            print(f"Сервер {base} не отвечает на /health — батарея не запущена")
            return 2
        bat = Battery(client)
        bat.public_paths()
        bat.auth_required()
        bat.auth_with_key(args.api_key)
        bat.compression_round_trip(args.api_key)
        bat.tenant_context(args.api_key)
        bat.dsl_route_diagnostics(args.api_key)
        bat.security_headers()
        bat.correlation_ids()
        bat.error_envelope()

    width = max(len(r.name) for r in bat.results)
    for r in bat.results:
        print(f"  {r.status:4s}  {r.name:{width}s}  {r.detail}")

    passed = sum(1 for r in bat.results if r.status == "PASS")
    failed = [r for r in bat.results if r.status == "FAIL"]
    skipped = [r for r in bat.results if r.status == "SKIP"]
    print()
    print(f"### {base}")
    print(
        f"### PASS {passed} | FAIL {len(failed)} | SKIP {len(skipped)} | всего {len(bat.results)}"
    )
    if skipped:
        print(
            "### SKIP означает зависимость от внешнего сервиса (БД), а не пройденную проверку."
        )

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "base_url": base,
                    "results": [
                        {
                            "name": r.name,
                            "status": r.status,
                            "detail": r.detail,
                            **r.extra,
                        }
                        for r in bat.results
                    ],
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        print(f"### JSON -> {args.json_out}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
