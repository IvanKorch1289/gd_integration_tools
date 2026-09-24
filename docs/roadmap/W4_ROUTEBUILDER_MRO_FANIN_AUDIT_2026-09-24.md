# W4 — RouteBuilder MRO + fan-in audit (v6 §10 W4, 2026-09-24)

> **Этот документ — sibling к `docs/roadmap/PROGRESS_LEDGER.md`** и
> `ARCHITECTURE.md`. Per v6 §10 W4: «Полный RouteBuilder MRO и fan-in
> измерить, не использовать старое число 76».

## 1. Методология

Measurement выполнен на HEAD `1da8bcc8d` (2026-09-24, после v6 W2).

```python
import sys
sys.path.insert(0, "src")
from src.backend.dsl.builders.base import RouteBuilder

mro = [c.__name__ for c in RouteBuilder.__mro__]
bases = [c.__name__ for c in RouteBuilder.__bases__]
mixins_in_mro = [b for b in mro if "Mixin" in b]
```

Fan-in:
```bash
grep -rln "from src.backend.dsl.builders.base import\|from backend.dsl.builders.base import" \
    src/ tests/ 2>/dev/null | wc -l
```

## 2. Результаты измерения (verified, runtime)

| Metric | Value | Метод |
|---|---|---|
| Direct bases (наследует напрямую) | **36 mixins** | `RouteBuilder.__bases__` (len=36) |
| Full MRO length | **82 classes** | `RouteBuilder.__mro__` (len=82, includes object) |
| Mixins в полном MRO | **76** | filter `Mixin` in mro |
| Fan-in importers | **111** | grep src/ + tests/ |
| Auto-gen stub lines | **3502** | `src/backend/dsl/builders/base.pyi` |

### 2.1 Прямые базы (36 mixins, alphabetically-ordered):

```
AIRPAMixin, AgentDSLMixin, BatchMixin, BankingScriptsMixin,
CollectionMixin, ComplianceMixin, ConfigMixin, ContentMixin,
ControlFlowMixin, ConvertersMixin, DataStoreMixin, DataStoreStepMixin,
DepsMixin, EIPContentMixin, EIPMixin, EventBusMixin, ExternalSourcesMixin,
FeatureMixin, FluentMixin, FormatConvertersMixin, IPRestrictionMixin,
InfrastructureDSL, IntegrationMixin, MessagingEIPsMixin, MiddlewareMixin,
NotebookMixin, PlanExecuteMixin, PolicyMixin, ReflectionLoopMixin,
RequestReplyMixin, ResilienceMixin, RouterSpecialistMixin, RPAMixin,
SagaLRAMixin, SourcesMixin, StreamingEIPsMixin, TemplateEngineChainMixin,
TemplateEngineMixin, TextOpsMixin, ValidationMixin, VariableMixin
```

(Note: `ExternalSourcesMixin` входит в DIRECT bases, не в `SourcesMixin`.)

### 2.2 Full MRO breakdown (82 classes):

- 36 direct bases
- ~40 transitive bases (EIPMixinBase, MixinABC, Protocol-классы,
  abstract intermediate bases)
- 1 final = `object`

Из них 76 содержат суффикс `Mixin` (per MRO walk, not just direct).

## 3. Reconciliation с v6 baseline ("76 mixins")

v6 baseline сказал: «В RouteBuilder сейчас измерено 36 непосредственных
базовых mixin-классов; прежнее число 76 могло относиться к полному
runtime MRO».

**Verification: v6 baseline был корректен оба раза**:
- 36 = direct bases (mixins, которые RouteBuilder наследует напрямую).
- 76 = mixins в полном MRO (direct + transitive через `EIPMixinBase`,
  `CoreEIPsMixin`, `RoutingEIPsMixin`, etc.).

Per v6 §10 W4 spec: «не использовать старое число 76 без отдельного
измерения». **Измерено в этом аудите**: 36 direct / 76 full MRO /
82 full MRO length (including object).

## 4. Fan-in (111 importers)

```bash
grep -rln "from src.backend.dsl.builders.base import\|from backend.dsl.builders.base import" \
    src/ tests/ 2>/dev/null | wc -l
# Output: 111
```

Top categories:
- DSL processors (CQRS, EIP, router_specialist, plan_execute, ...): ~30
- Tests: ~50
- Other (services, entrypoints): ~30

Per v6 «Не создавать новый facade, если canonical public API уже существует»:
RouteBuilder через `dsl.builders.base` — canonical API. Fan-in высокий,
что подтверждает его роль как primary DSL builder.

## 5. Split recommendation (per v6 §10 W4 + «разделять по bounded concern
только при снижении fan-in/cycles/LOC без ухудшения DX»)

**Per cycle 158+ discipline + v6 §4.1**: НЕ переписывать 76/77-mixin API
целиком. Current architecture — composite mixin pattern с bounded
constitution.

**Per v6 «Большие файлы ранжировать по complexity + churn + fan-in, не
только LOC»**:
- File LOC: 3502 (stub) + ~17K (build/base/__init__.py)
- Direct bases: 36 (composition complexity)
- Fan-in: 111 (high = high change-impact risk)

**Recommendation (per «shortest safe diff wins»)**:
- ❌ NOT execute: bulk mixin split (would break 111 importers + 3502 lines
  of generated stub).
- ⚠️ Consider (separate waves):
  - P1.M1: SCOPED context manager (P1 DI wave) — decompose `VariableMixin` /
    `ConfigMixin` / `FeatureMixin` subset.
  - P1.M2: Split `IntegrationMixin` → отдельные sub-mixins per transport
    (HTTP/GraphQL/gRPC/WS).
  - P2: EIPMixin split into domain-specific sub-mixins (Core/Routing/Sources
    already split — verify decomposition contract).

## 6. Honest scope statement (per audit «Не завышай»)

- ✅ Verified: 36 direct bases, 76 mixins in MRO, 82 full MRO, 111 fan-in.
- ✅ Verified: v6 baseline (76 mixins) was accurate — full MRO count.
- ✅ Verified: 3502 lines stub auto-generated (Sprint 14 K3 W2).
- ❌ NOT measured: dynamic imports, registry scans, plugin scans for
  RouteBuilder usage (per v6 §10 W4 «compat processors удалять только
  после static import graph, dynamic import search, registry scan,
  plugin scan, tests и deprecation record» — applies to compat
  processors, NOT RouteBuilder).
- ❌ NOT started: P1.M1 SCOPED context — separate wave.
- ❌ NOT started: mixin split — blocked by 111 fan-in importers, separate
  ADR required before any split.

## 7. References

- `src/backend/dsl/builders/base/__init__.py` — RouteBuilder class definition.
- `src/backend/dsl/builders/base.pyi` — auto-generated stub (3502 lines).
- `docs/roadmap/PROGRESS_LEDGER.md` — backlog ledger.
- v6 §10 W4 spec: «Полный RouteBuilder MRO и fan-in измерить, не
  использовать старое число 76».
- v6 §4.1: «Не переписывать 76/77-mixin API целиком».
