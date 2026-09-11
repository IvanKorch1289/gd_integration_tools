# Library Replacement Analysis — 2026-09-11

> Задача: найти библиотеки, способные заменить кастомные функции репозитория
> (пример постановки: fabric для SSH). Критерий отбора: только зрелые,
> стабильные, безопасные. Правила программы: смена зависимости требует
> проверки license/support/security/API/тестов (§0.6 директивы) и координации
> по uv.lock — поэтому этот документ = анализ и план, НЕ массовая замена.
> Evidence: grep/creosote/pip-audit на HEAD `ca6d68f55`, PyPI-проверки 2026-09-11.

## 0. Вердикт кратко

**Репозиторий уже library-first.** Проверка по всем областям показала: там,
где существует зрелая библиотека, проект использует её через тонкий
домен-фасад; самописный код — это (а) осознанный stdlib-YAGNI с задокументированным
решением, (б) security-мотивированная реализация, или (в) тонкие protocol-адаптеры.
Пример из постановки (SSH/fabric) уже закрыт: SSH/SFTP работают на **asyncssh** —
асинхронном индустриальном стандарте; fabric (синхронная обёртка над paramiko)
был бы деградацией для async-first шины.

## 1. SSH / SFTP (пример постановки)

| Позиция | Факт | Вердикт |
|---|---|---|
| SFTP-клиент | `infrastructure/clients/transport/sftp.py` — фасад над **asyncssh** (connect/start_sftp_client/put/get/readdir) + breaker + retry; known_hosts strict-mode с fail-closed вне dev_light | **KEEP asyncssh** |
| SSH-команды | `dsl/engine/processors/ssh_command.py` — процессор `ssh_exec` на asyncssh | KEEP |
| fabric | Sync-обёртка над paramiko; не даёт преимуществ async-шине; вводил бы второй SSH-стек | **NO_ACTION** |

Зрелость asyncssh: 2.24.0 (релизы 2026 г., непрерывная история с 2014),
Production/Stable, py≥3.10, EPL-2.0/GPL-2.0+ dual, post-quantum KEX (ML-KEM),
X.509/FIDO2. Замечание: проект одного автора (Ron Frederick) — bus-factor 1;
компенсация: код изолирован в 2 файлах-фасадах, смена на paramiko/async-process
локальна. pip-audit: 0 CVE по asyncssh.

## 2. Локальные команды (TerminalExecProcessor)

`dsl/engine/processors/rpa/system.py:157` — asyncio subprocess + timeout.
Зрелой библиотеки, превосходящей stdlib `asyncio.create_subprocess_exec` +
`wait_for` для локальных команд, нет (fabric/sh — про shell/SSH и sync).
**KEEP stdlib** (63 LOC, ponytail: stdlib первым).

## 3. Retry / Rate-limit / Scheduler — уже библиотеки

| Область | Кастомное | Библиотека (статус) | Вердикт |
|---|---|---|---|
| Retry | `core/resilience/retry.py` (293 LOC) — **тонкая декларативная обёртка над tenacity.AsyncRetrying** (17 потребителей) | tenacity 9.1.4 = последний релиз (2026-02, Apache-2.0, py3.10–3.14) | KEEP; консолидация: 6 файлов используют tenacity напрямую, мимо фасада — внутренняя унификация, не замена библиотеки |
| Rate-limit | `infrastructure/resilience/unified_rate_limiter.py` | **pyrate-limiter 4.5.0** (4 файла-потребителя) | KEEP |
| Scheduler | фасады `core/scheduler` | apscheduler 3.11.3 (11 файлов) | KEEP |
| Cron | валидация расписаний | croniter 6.2.4 (2 файла) | KEEP |
| File-watch | `file_watcher.py` поверх | watchdog 6.0.0 | KEEP |

## 4. Кэш — обратный кандидат: заменить БИБЛИОТЕКУ на свою реализацию

| Позиция | Факт | Вердикт |
|---|---|---|
| `infrastructure/cache/backends/` | 5 тонких адаптеров (91–210 LOC) под CacheBackend-протокол: redis/keydb/memcached/memory/disk | KEEP (это и есть интеграционный слой) |
| `infrastructure/cache/backends/disk.py` (132 LOC) | Самописный: sha256-шардирование, JSON-bytes значения, **без pickle** | **KEEP** — сознательно безопаснее библиотеки |
| `diskcache` 5.6.3 | Был в deps ради единственного потребителя `decorators/caching/storage/disk.py`; нёс **PYSEC-2026-2447** (pickle-RCE при записи в cache dir; fix-версии нет; ADR-0287) | **✅ ВЫПОЛНЕНО 2026-09-11**: перепроверено на PyPI/OSV — последний релиз 5.6.3 = last_affected, upstream неактивен (GitHub Releases пуст). Потребитель переписан на собственный pickle-free `_IndexedByteStore` (sha256-файлы + JSON-индекс), **diskcache удалён из deps**; pip-audit = 0 findings, allowlist очищен (0 entries). Ограничение: индекс per-process (был sqlite) — для default-OFF fallback приемлемо |
| `cachetools` 7.1.8 | MemoryBackend — тонкая обёртка TTL | KEEP |

## 5. Прочие проверенные области

| Область | Факт | Вердикт |
|---|---|---|
| Encoding-detect (41 LOC) | stdlib BOM/UTF-8 check; решение Ponytail YAGNI **D277** задокументировано; charset-normalizer в deps (нужен httpx) | NO_ACTION |
| MIME-detect (64 LOC) | stdlib-обёртка | NO_ACTION |
| Singleflight (stampede.py, 34 LOC) | asyncio-локи | NO_ACTION |
| Неиспользуемые deps | creosote: **«No unused dependencies found»** (filelock — транзитивная, 0 прямых импортов — норма) | NO_ACTION |
| JSON/UUID/JWT/PII/HTTP/валидация | orjson, uuid-utils, joserfc, presidio, httpx, jsonschema — уже библиотеки | KEEP |

## 6. Supply-chain замечания

1. **pip-audit на весь venv: единственный CVE — diskcache** (allowlist, G12 PASS).
   Это сильное свидетельство безопасности остального стека.
2. Виртуозных «переизобретений» не найдено: то, что выглядит кастомным,
   — фасад (retry→tenacity, rate→pyrate-limiter) или security-выбор (disk-cache
   без pickle).
3. Рекомендация-долг: CI-запрет новых `type: ignore[call-arg|arg-type]`
   (урок Sprint-ре-верификации) — см. FINAL_REPORT §4.

## 7. План (если принимать)

| Шаг | Действие | Статус |
|---|---|---|
| 1 | diskcache → собственный pickle-free backend; удаление из deps; allowlist 0 entries | **✅ выполнено 2026-09-11** (pip-audit 0) |
| 2 | Унификация: 6 прямых tenacity-файлов → фасад `core.resilience.retry` | открыт (refactor, не срочно) |
| 3 | SSH/SFTP/TerminalExec/cache-адаптеры/encoding — без изменений | — |
