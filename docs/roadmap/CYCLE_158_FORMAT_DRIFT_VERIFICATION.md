# Cycle 158+ format-drift verification (2026-09-23)

> **Этот документ — verification artifact** для проверки, что cycle 158+
> commits НЕ добавили new format drift.

## 1. Замер

```
$ make format-check
176 files would be reformatted, 2348 files already formatted
Ruff formatting failed! Run 'make fix' to auto-format your code.
make: *** [make/formatting.mk:12: format-check] Ошибка 1
```

**Config**: `target-version = "py314"` (per pyproject.toml).

## 2. Cycle 158+ файлы — none в failure list

**Files added/modified this session** (24 atomic commits, 19 файлов):

```
ai_policies/agent_basic.policy.yaml
docs/adr/0341-w2-p1-2-legacy-processors-inventory.md
docs/adr/0342-ai-policy-spec-s76-tool-policy-migration.md
docs/adr/0343-pluginmanifest-schema-evolution-core-admin-dadata-skb.md
docs/adr/0344-sagalra-convergence-plan.md
docs/adr/INDEX.md
docs/roadmap/CYCLE_158_PLUS_HANDOFF.md
docs/roadmap/PROGRESS_LEDGER.md
extensions/core_admin/plugin.toml
extensions/dadata/plugin.toml
extensions/skb/plugin.toml
tests/unit/tools/test_startup_time_gate.py
tests/unit/tools/test_w11_p0_3_check_compat.py
tests/unit/tools/test_w11_p0_3_check_feature_flag_dependencies.py
tests/unit/tools/test_w11_p3_2_audit_legacy_processors.py
tools/audit_legacy_processors.py
tools/checks/check_compat.py
tools/checks/check_feature_flag_dependencies.py
tools/checks/startup_time.py
```

**Cross-check с format-failure list** (174 unique files):

```
$ comm -12 <(sort session_files.txt) <(sort format_failures.txt)
(empty — 0 overlap)
```

**Verdict**: 0 of my session files в format failures. **Cycle 158+ не contributed к format drift.**

## 3. Pre-existing format drift (NOT this session's debt)

176 файлов (174 unique) needs reformat — **найдено до cycle 158+, существовало в
baseline `c262f1ba0` и ранее**.

Per baseline item (CLAUDE.md section 8):
> "except A, B: больше нет в src и tests; migration check → 0. Не повторяй
> прежний FALSE_CLAIM о «148 непарсящихся модулях»: в Python 3.14 эта
> форма разрешена PEP 758, а проект дополнительно мигрировал её на
> скобочную форму."

**Possible cause of drift**: `ruff format` с `target-version = "py314"`
может быть configured для auto-converting bracketed `except (A, B):`
обратно в PEP 758 bare `except A, B:` form. Если project convention =
bracket form, тогда ruff format auto-un-migrates что не соответствует
project standard.

Sample from format_check output:
```
--- src/backend/core/ai/security/workflow_hooks.py
+++ src/backend/core/ai/security/workflow_hooks.py
@@ -122,7 +122,7 @@
         )
         try:
             resolved = Path(file_path).resolve()
-        except (OSError, ValueError):
+        except OSError, ValueError:
```

`except OSError, ValueError:` — Python 2 syntax (invalid для Python 3.13+).
Если ruff format выводит это как `+`, configuration возможно нацелена
на заведомо не-Python-3.14 версию для **except** statement (что противоречит
PEP 758's optional bracket-less form).

## 4. Status per v4 §10

- ❌ Format drift: **NOT CLOSED** (176 files need reformat).
- ⚠️ Root cause unknown: возможно ruff format configuration противоречит
  project convention. Не исправлено в этой сессии (out of scope).
- ✅ New debt added by cycle 158+: **0**.

## 5. References

- pyproject.toml `[tool.ruff]` config (target-version, line-length).
- Baseline item CLAUDE.md section 8 (PEP 758 / bracket form migration).
- CYCLE_158_PLUS_HANDOFF.md — Priority recommendations для next cycles.
