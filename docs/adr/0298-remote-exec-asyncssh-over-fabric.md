# ADR-0298: Удалённое исполнение — остаёмся на asyncssh; Fabric отклонён (sync-only)

**Дата**: 2026-09-06
**Статус**: accepted (interim — контекст запрошен пользователем: «изучи Fabric и спланируй миграцию, если текущая реализация неудобная»)
**Supersedes**: —
**Related**: ADR-0293 (mypy permissive/strict), AGENTS.md (async-first, mandatory)

## Контекст

Запрошено: изучить Fabric (docs.fabfile.org, 2.x/3.x) для выполнения удалённых
команд и сравнить с текущей реализацией проекта; при неудобстве текущей —
спланировать аккуратную миграцию.

**Текущие поверхности удалённого исполнения** (все на asyncssh, кроме FTP):

| Поверхность | Расположение | Транспорт | Статус |
|---|---|---|---|
| `SshCommandProcessor` (DSL `ssh_exec`) | `dsl/engine/processors/ssh_command.py` (243 LOC) | asyncssh.connect per-call | ✓ mature: capability-gate, audit, known_hosts fail-closed, key/password auth |
| `SftpClient` (инфраструктура) | `infrastructure/clients/transport/sftp.py` (269 LOC) | asyncssh + SFTP session | ✓ upload/download/list/download_bytes, known_hosts resolver |
| `FtpUploadProcessor` (RPA) | `dsl/engine/processors/rpa/operations/ftpuploadprocessor.py` | ftplib FTP/FTPS в `asyncio.to_thread` | ✓ sync-либа корректно вынесена из event loop |
| `TerminalExecProcessor` (RPA) | локальный subprocess (shell=False, gated) | — | не SSH |

**Fabric (2.x/3.x) — факты из документации**:
- Полностью **синхронный** фреймворк (paramiko-based); async/await API
  **отсутствует** на всех документированных поверхностях (Connection, runners,
  tasks, group).
- `Connection` — ленивое подключение с кэшированием; `run/sudo/put/get`;
  layered config + чтение ssh_config; `inline_ssh_env` (3.x default True,
  БЕЗ shell-escaping — CVE-класс питуалов).
- Мультихост: `SerialGroup`/`ParallelGroup` (sync; parallel — через threads).
- `fab` CLI — tasks-дискавери, роли, runtime host-lists.

## Рассмотренные варианты

### Вариант A — миграция runtime (SshCommandProcessor/SftpClient) на Fabric. ОТКЛОНЁН

1. **Конфликт с mandatory-правилом async-first** (AGENTS.md): Fabric sync.
   Вызов `conn.run()` внутри `async def process()` блокирует event loop —
   недопустимо для шины под нагрузкой. Обход через `asyncio.to_thread` на
   каждый вызов — двойная обёртка (thread + sync-fabric) ради библиотеки,
   дающей то же самое, что уже есть.
2. **Регрессия функционала**: потеря нативного async-стрима stdout/stderr
   (`conn.run` в asyncssh стримит), async known_hosts-политики (fail-closed
   resolver Cycle 33 DS3), capability-gate и audit-интеграции.
3. **Fabric-специфичные риски**: `inline_ssh_env=True` (default 3.x) подставляет
   env-префиксы в command string без escaping; thread-based ParallelGroup
   несовместим с single-event-loop моделью DSL.
4. **Реальный профиль использования**: DSL `ssh_exec` — одно сообщение = одна
   команда на одном хосте. Дифференциаторы Fabric (роли, fabfile-таски,
   мультихост-группы, ssh_config layering) не используются ни одним сценарием.

### Вариант B — гибрид: Fabric только для ops/CLI-слоя. ОТЛОЖЕН (YAGNI)

Sync-контекст (manage.py, деплой-скрипты) — единственное место, где Fabric
идиоматичен. Но такого требования в проекте сейчас нет: деплой — make + CI;
админ-диагностика хостов — через DSL `ssh_exec`/RPA. Заводить зависимость и
fabfile-слой «на будущее» нарушает ponytail/YAGNI. Возрождается одной
командой `uv add fabric`, если появится fleet-ops требование.

### Вариант C — принят: остаёмся на asyncssh + точечные улучшения

Текущая реализация покрывает потребности и имеет зрелые защитные механизмы.
Точечные улучшения (вне этого ADR, по мере надобности):
- переиспользование SSH-соединения между сообщениями одного route (pool
  на asyncssh-connection) — только при подтверждённой нагрузочной потребности;
- при появлении fleet-ops требований — Вариант B (Fabric в ops-CLI слое,
  не в runtime).

## Последствия

- Runtime удалённого исполнения остаётся на asyncssh (async-native, mature,
  gated, audited). Fabric в зависимости проекта не добавляется.
- ADR-0297 (Frontend migration, сессия-2) с данным ADR не связан;
  коллизия номера устранена перенумерацией в ADR-0297.
- Если пользователь подтвердит потребность в Fabric (fleet-ops/CLI) —
  план миграции: (1) `uv add fabric` в dev/ops extra; (2) fabfile-слой
  в `manage.py`/ops-скриптах; (3) запрет импорта fabric в
  `src/backend/{dsl,services,infrastructure}` (check_layers-правило) —
  runtime остаётся на asyncssh.

## Ссылки

- Fabric docs: docs.fabfile.org (Connection, group, runners, tasks; sync-only)
- `dsl/engine/processors/ssh_command.py` (Cycle 33 DS3 known_hosts fail-closed)
- `infrastructure/clients/transport/sftp.py`
- AGENTS.md: async-first, no blocking I/O in async context (mandatory)
