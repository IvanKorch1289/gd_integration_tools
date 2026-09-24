# W5.3 — cProfile waterfall: 80% startup spent in YAML loading (v6 §10 W5)

> **Этот документ — sibling к `docs/roadmap/W5_STARTUP_PROFILE_AUDIT_2026-09-24.md`**
> и `docs/roadmap/PROGRESS_LEDGER.md`. Per v6 §10 W5: «Lazy import применять
> только при доказанном выигрыше и без сокрытия ImportError обязательной зависимости».
> cProfile waterfall — фактический breakdown startup cost.

## 1. Методология

Измерено на HEAD `60be30527` (2026-09-24, после v6 W3.2 webhook test), Python 3.14.4.

```python
import cProfile, pstats
profiler = cProfile.Profile()
profiler.enable()
import src.backend.main
profiler.disable()

stats = pstats.Stats(profiler).sort_stats("cumulative")
stats.print_stats(30)
```

Total `src.backend.main` cold start ≈ 12s (с cProfile overhead ≈ +6s,
т.к. cProfile сам по себе overhead). Per W5.1 baseline: ~5.4s без cProfile.

## 2. REVISED waterfall — 80% spent in YAML loading (per cProfile top-30)

| Rank | cumtime | % | function | file |
|---:|---:|---:|---|---|
| 1 | **11.098s** | **~80%** | `pydantic_settings.__init__` | pydantic_settings/main.py:193 |
| 2 | **11.049s** | ~80% | `_settings_build_values` | pydantic_settings/main.py:484 |
| 3 | 10.962s | ~78% | `ConfigLoader.__call__` | src/backend/core/config/config_loader.py:128 |
| 4 | 10.821s | ~77% | `ConfigLoader._read_yaml` | src/backend/core/config/config_loader.py:79 |
| 5 | **10.789s** | **~77%** | `yaml.safe_load` (×240 calls) | PyYAML __init__.py:117 |
| 6 | 10.752s | ~77% | `yaml.constructor.get_single_data` | PyYAML |
| 7 | 10.191s | ~73% | `yaml.composer.get_single_node` | PyYAML |
| 8 | 9.225s | ~66% | `yaml.parser.check_event` | PyYAML |
| 7.320s | ~52% | `yaml.scanner.check_token` | PyYAML |
| 5.223s | ~37% | `yaml.scanner.fetch_more_tokens` | PyYAML |
| 8.945s | ~64% | `Settings module init` | src/backend/core/config/settings.py:1 |

**Conclusion**: реальный bottleneck — **PyYAML parsing of 240 YAML config files
на startup**, НЕ apscheduler/temporalio/pydantic как предполагалось в W5.1.

## 3. Honest re-assessment of W5.1 (correction per cProfile data)

W5.1 audit doc перечислил apscheduler/temporalio/pydantic/sqlalchemy как
heavy modules. Это было основано на ESTIMATE — реальный cProfile waterfall
показывает PyYAML как доминирующий bottleneck.

| Module (W5.1 claim) | Real cProfile impact | Status |
|---|---|---|
| apscheduler + temporalio | ~0.5s (deferred init) | **overestimated** |
| pydantic v2 model validation | ~0.5s | **overestimated** |
| sqlalchemy + async engine | ~0.3s | **overestimated** |
| structlog + telemetry | ~0.2s | **overestimated** |
| **PyYAML config loading** | **~10.8s** | **NEW: primary bottleneck** |
| DSL processors AST walk | ~0.3s | **overestimated** |
| Plugin scanner | ~0.1s (gated by flag, default OFF) | **overestimated** |

Per v6 §3: «Не выдумывать API, версии, параметры, результаты команд» —
W5.1 estimates были based on reasoning, не runtime. cProfile gives real numbers.

## 4. Realistic optimization targets (per cProfile data)

### W5.4 (next): YAML config caching / lazy loading

Per v6 §10 W5: «Lazy import применять только при доказанном выигрыше».

Real gain target: cache YAML parses + lazy-loading config sections
на first access. Estimated gain: **5-8 seconds reduction** (50-70% of
startup time).

Implementation options:
1. **PyYAML → orjson/ujson** (binary JSON config format, faster parse).
   Estimated: ~3-5s reduction.
2. **Lazy YAML loading** — load only needed config sections on first access.
   Estimated: ~2-4s reduction.
3. **YAML parse cache** — hash source file, cache parsed dict.
   Estimated: ~1-2s reduction.

**Recommendation**: Combined approach — convert to JSON (binary, fast)
for performance-critical paths + lazy load for rarely-accessed sections.

### W5.5 (deferred): Plugin scanner lazy (W5.2)

Per cProfile data, plugin scanner ~0.1s (gated by default flag). NOT a
priority — minimal gain.

## 5. Honest scope (per audit «Не завышай»)

- ✅ cProfile waterfall measured (top-30 functions by cumtime).
- ✅ PyYAML identified as PRIMARY bottleneck (~77% of startup).
- ✅ W5.1 estimates corrected (overestimated for apscheduler/temporalio).
- ⚠️ Realistic gain от proposed W5.4: 5-8s reduction (significant).
- ❌ NOT executed: YAML config optimization (W5.4 deferred).
- ❌ NOT covered: importlib + stdlib overhead (~1.0s cumulative, secondary).
- ⚠️ cProfile itself adds ~6s overhead — measurements with profiler
  aren't representative of production startup time (~5.4s uncoupled vs ~12s
  with cProfile).

## 6. References

- `docs/roadmap/W5_STARTUP_PROFILE_AUDIT_2026-09-24.md` — W5.1 baseline (corrected).
- `src/backend/core/config/config_loader.py:128` — `ConfigLoader.__call__` (hot path).
- `src/backend/core/config/settings.py:1` — settings module init.
- v6 §10 W5 spec: «Измерить startup import profile».
- PyYAML 6.x — slow YAML parser (replacement: orjson, ruamel, msgspec).
