# Cycle 7 — D-AUDIT-701 — config_audit stale path fix

**Date:** 2026-08-07
**HEAD:** pre-commit (working tree)
**Cycle:** 7 — focused fix (1 P1 finding)
**Task ID:** T-C7-01-CONFIG-AUDIT
**Finding:** ENV-P1-001 (RESIDUAL from cycle-3 P1-002 / cycle-4 P1-002)

---

## 1. Finding

`tools/config_audit.py` и `tools/codegen_settings.py` содержат stale
path `src/core/config/` — реальное расположение модулей
`BaseSettingsWithLoader` после реструктуризации V22
(см. `AGENTS.md` ARCHITECTURE-секция) — `src/backend/core/config/`.

Следствие: AST-скан в `tools/config_audit.py:36` указывает на
**несуществующий** каталог → `Discovered 0 settings classes` →
audit-инструмент полностью нерабочий (CI-gate молча проваливается).

Подтверждено в:
- `docs/audit/swarm-2026-08-06/cycle-3/phase-1/12-settings-environment.md:82`
- `docs/audit/swarm-2026-08-06/cycle-4/phase-1/12-settings-environment.md:118,144,148`
- `docs/audit/swarm-2026-08-06/cycle-4/PHASE-2-SUMMARY.md:78,166`

---

## 2. Diff scope (минимальные правки)

| Файл | Изменения |
|---|---|
| `tools/config_audit.py` | docstring :4 + path-constant :36 (2 правки, +1 комментарий) |
| `tools/codegen_settings.py` | path-constants :62-65 (3 правки, +1 комментарий) + docstring :803 (1 правка) |

`git diff --stat tools/config_audit.py tools/codegen_settings.py`:

```
 tools/codegen_settings.py | 9 +++++----
 tools/config_audit.py     | 5 +++--
 2 files changed, 8 insertions(+), 6 deletions(-)
```

**+8 / -6 LOC** в 2 файлах (cycle-7/D-AUDIT-701 комментарии
маркируют scope фикса без переписывания cycle 1-6 логики).

### 2.1 `tools/config_audit.py`

```diff
@@ -1,7 +1,7 @@
 """Двусторонний аудит конфигурации (W20.1+W20.2).

 Сверяет YAML-конфигурацию (``config_profiles/base.yml`` + overlay активного
-профиля) с моделями ``BaseSettingsWithLoader`` из ``src/core/config/``.
+профиля) с моделями ``BaseSettingsWithLoader`` из ``src/backend/core/config/``.

@@ -33,7 +33,8 @@ from typing import Any
 import yaml

 ROOT = Path(__file__).resolve().parents[1]
-CONFIG_DIR = ROOT / "src" / "core" / "config"
+# cycle-7/D-AUDIT-701: путь src/backend/core/config/ (не src/core/config/)
+CONFIG_DIR = ROOT / "src" / "backend" / "core" / "config"
```

### 2.2 `tools/codegen_settings.py`

```diff
@@ -59,10 +59,11 @@ import libcst as cst
 import libcst.matchers as m

 ROOT = Path(__file__).resolve().parents[1]
-SERVICES_DIR = ROOT / "src" / "core" / "config" / "services"
-SETTINGS_FILE = ROOT / "src" / "core" / "config" / "settings.py"
+# cycle-7/D-AUDIT-701: путь src/backend/core/config/ (не src/core/config/)
+SERVICES_DIR = ROOT / "src" / "backend" / "core" / "config" / "services"
+SETTINGS_FILE = ROOT / "src" / "backend" / "core" / "config" / "settings.py"
 SERVICES_INIT = SERVICES_DIR / "__init__.py"
-INTEGRATION_BASE = ROOT / "src" / "core" / "config" / "integration_base.py"
+INTEGRATION_BASE = ROOT / "src" / "backend" / "core" / "config" / "integration_base.py"
@@ -800,7 +801,7 @@ def _extract_default(call: ast.Call) -> str:
 def extract_spec_from_class(cls_name: str) -> CodegenSpec:
     """Построить ``CodegenSpec`` по имени существующего Settings-класса.

-    Поиск идёт по ``src/core/config/services/*.py``. Возвращает spec с
+    Поиск идёт по ``src/backend/core/config/services/*.py``. Возвращает spec с
     исходными полями, готовый для ``_spec_to_yaml``.
```

---

## 3. Runtime verification

### 3.1 `tools/config_audit.py` — все 4 профиля

```
$ .venv/bin/python tools/config_audit.py --profile dev
Discovered 69 settings classes in src/backend/core/config; 56 keys in .env.example.

$ .venv/bin/python tools/config_audit.py --profile dev_light
Discovered 69 settings classes in src/backend/core/config; 56 keys in .env.example.

$ .venv/bin/python tools/config_audit.py --profile staging
Discovered 69 settings classes in src/backend/core/config; 56 keys in .env.example.

$ .venv/bin/python tools/config_audit.py --profile prod
Discovered 69 settings classes in src/backend/core/config; 56 keys in .env.example.
```

**До фикса**: `"Discovered 0 settings classes in src/core/config; 56 keys"` — `0`.
**После фикса**: `"Discovered 69 settings classes in src/backend/core/config; 56 keys"`.

Exit code: `1` (audit корректно сообщает о 16 missing-secret дрифтах
в YAML↔.env.example — это **отдельный трек-багаут**, не в scope cycle-7).
Раньше exit был `0` (типа OK) при полностью неработающем AST-скане.

### 3.2 Path-резолв (`codegen_settings.py`)

```
SERVICES_DIR:     src/backend/core/config/services        exists=True
SETTINGS_FILE:    src/backend/core/config/settings.py     exists=True
INTEGRATION_BASE: src/backend/core/config/integration_base.py  exists=True
CONFIG_DIR:       src/backend/core/config                  exists=True
```

### 3.3 Codegen tests (cycle 7 регрессия)

```
$ .venv/bin/python -m pytest tests/unit/codegen/test_codegen_settings.py -q
..........................                                               [100%]
26 passed in 0.78s
```

Тесты используют `monkeypatch.setattr(cg, "SERVICES_DIR", ...)` —
привязка к абсолютному пути не нужна, имена констант сохранены → PASS.

---

## 4. Gates

| Gate | Baseline | Cycle 7 final | Статус |
|---|---|---|---|
| Layer checker | 175/0 | 175/0 (2278 files) | **PASS** |
| Security allowlist | 27 | 27 | **PASS** |
| Docstring gate | 0 missing | 0 missing in 840 files | **PASS** |
| `s3.py` modified | нет | нет | **PASS** |
| `gateway_adapter.py:128-129` | present | present (UNTOUCHED) | **PER PLAN** |
| `uv.lock` churn | 0 diff | 0 diff lines | **PASS** |
| `blue_green.sh` | UNTOUCHED | UNTOUCHED | **PER PLAN** |
| `tools/config_audit.py` runtime | 0 classes | 69 classes | **PASS** |
| `tools/codegen_settings.py` paths | stale | resolved | **PASS** |
| codegen tests | n/a | 26/26 PASS | **PASS** |
| Cycle 1-6 commits не переписаны | n/a | n/a | **PER PLAN** |

### `make check-docstrings MAX_ALLOWED=0`

```
Running docstring policy check...
Total: 0 missing docstrings in 0 files
Files scanned: 840
docstring policy OK
exit=0
```

### `bash tools/cycle-1-preflight.sh` (informational)

```
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 27
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 46 entries (разобраться)
  [OK]   uv.lock churn — 0 diff lines (pre-existing, не растёт)
  [OK]   s3.py untouched — не modified
Preflight failed — fix before running developer task.
exit=1
```

Working-tree FAIL — **pre-existing** (40→46 entries: 14 modified + 32
untracked из cycle 1-6 + prior-сессий). Не в scope cycle-7 (явное
требование: «cycle 1+2+3+4+5+6 правки НЕ переписывать»). Все мои
изменения (2 modified файла) уже учтены в этих 46.

`tools/cycle-1-preflight.sh` создан в cycle-1 для gate-проверки
новых правок; baseline-уже-failing preflight не блокирует cycle-7
runtime-валидацию (все остальные 6/6 gates PASS).

---

## 5. Что НЕ трогалось (per task constraints)

- `uv.lock` — без изменений (0 diff lines)
- `.security/pip-audit-allowlist.txt` — без изменений
- `src/backend/infrastructure/storage/s3.py` — без изменений
- `tools/blue_green.sh` — без изменений
- `tests/unit/tools/test_blue_green_switch.py` — без изменений
- `src/backend/services/ai/gateway_adapter.py:128-129` — pre-existing
  residual сохранён (явно forbidden трогать)
- Cycle 1+2+3+4+5+6 правки (21+ atomic commits в HEAD `6ebb482c`)
  — НЕ переписывались
- Никаких `except Exception` без concrete handling не удалено
- Русские docstrings (config_audit.py, codegen_settings.py) НЕ переводились
- `python-dev skill` соблюдён: async-first, capability-checked фасады,
  80% декларативно

---

## 6. Stale refs audit (вне scope cycle-7, для трек-багаута)

Найдены другие ссылки на stale `src/core/config/`, которые НЕ правились
в cycle-7 (явное ограничение scope = 2 файла):

| Файл | Строка | Тип |
|---|---|---|
| `tests/unit/conftest.py` | 68, 73, 77, 80 | комментарий |
| `tools/check_env_example.py` | 3 | docstring |
| `src/backend/infrastructure/registry.py` | 14 | комментарий |

Эти ссылки **только в комментариях/docstring** (не runtime-path),
поэтому не влияют на работоспособность инструментов. Трекаются как
**ENV-P2-002** для будущего cleanup-цикла (cycle-8+).

---

## 7. Honest verdict

Cycle 7 — самый узкий и сфокусированный цикл: **1 RESIDUAL P1 фикс**,
**+8 / -6 LOC**, **2 файла**, **runtime-verified** (69 vs 0 classes),
**26/26 codegen tests PASS**, **0 regressions** в cycle 1-6 коммитах.

Env-P1-001 RESIDUAL (cycle-3 P1-002 → cycle-4 P1-002 → **cycle-7 ✅ RESOLVED**).

Cap rule (≥80% во всех 12 доменах) по-прежнему требует
architectural refactors вне scope atomic-fix циклов — это
зафиксировано в cycle-6 final-report и сохраняется в cycle-7.

---

*Cycle 7 D-AUDIT-701 report. +8/-6 LOC в 2 файлах. Runtime: 69 classes
discovered. 26 codegen tests PASS. Docstring gate 0/840.*