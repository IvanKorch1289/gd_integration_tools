# ADR-023 — NotificationGateway: единый transport-gate для уведомлений

- **Статус:** Accepted
- **Дата:** 2026-04-21
- **Фаза:** IL2.2 (Infrastructure Layer P1 — консолидация)
- **Связанные ADR:** ADR-022 (ConnectorRegistry), ADR-011 (Outbox), ADR-031 (multi-provider в O1).

## Контекст

До IL2.2 уведомления ходили через `src/services/ops/notification_hub.py` +
`notification_adapters.py` — Protocol-based Hub с Email / eXpress / Telegram /
Webhook. Это работало, но имеет 3 архитектурные проблемы:

1. **Место неправильное:** Hub живёт в `services/ops/`, хотя сами по себе
   email/SMS/IM — это **transport-concerns** (infrastructure). Бизнес-логика
   («кому слать / что слать / по какому событию») — в DSL и в services, а
   transport должен быть отделён.
2. **Нет шаблонизации:** каждый caller формирует subject/body вручную —
   дубликация, опечатки, нет версионирования сообщений, нет локализации
   (ru/en).
3. **Нет гарантий доставки:** при ошибке провайдера retry ложится на caller,
   а если его нет — сообщение теряется. Нет dead-letter-queue, нет replay.
4. **Без приоритетов:** transactional (код подтверждения для банковской
   операции) и marketing (рассылка обновлений) делят один pool — marketing-
   пик может задеть tx-SLA.

Коммерческие ESB решают это через **Notification Channel Gateway**:
MuleSoft Notification Connector + Email Module + Slack Connector; WSO2
Event-Sink chain с DLQ; TIBCO BusinessWorks Notification Service.

## Решение

### Расположение

Перенос в `src/infrastructure/notifications/`. В `services/ops/
notification_hub.py` остаётся **deprecation shim** на один релиз
(удаление в H3_PLUS). Бизнес-логика — кому/когда/что — остаётся в
services и DSL.

### Архитектура

```
     ┌──────────────────── DSL / service caller ────────────────────┐
     │   gateway.send_tx(channel="sms", template_key="kyc_approved",│
     │                   locale="ru", context={"name": "Иван"})     │
     └────────────────────────────┬─────────────────────────────────┘
                                  │
               ┌──────────────────▼────────────────────┐
               │  NotificationGateway                  │
               │  .send(channel, template_key, locale, │
               │        context, priority, idempotency)│
               └────┬──────────────┬──────────────────┬┘
                    │              │                  │
          ┌─────────▼──┐   ┌───────▼───────┐  ┌──────▼──────────┐
          │ Priority   │   │ TemplateRegistry│  │ DLQ repository │
          │ Router     │   │ (Jinja2+i18n)  │  │ (Postgres table)│
          │ tx | mkt   │   └───────┬────────┘  └────────────────┘
          └────┬───────┘           │
               │                   │
    ┌──────────▼───────────────────▼──────┐
    │  NotificationChannel adapters       │
    │  email | sms | slack | teams |      │
    │  telegram | webhook | express       │
    └─────────────────────────────────────┘
```

### Ключевые элементы

1. **`NotificationGateway`** — главный фасад. API:
   ```python
   async def send(
       channel: ChannelKind,          # "email" | "sms" | "slack" | "teams" | ...
       template_key: str,             # "kyc_approved"
       locale: str = "ru",
       context: dict = ...,           # для Jinja2 rendering
       recipient: str = ...,          # email / phone / chat_id
       priority: Priority = "tx",     # "tx" | "marketing"
       idempotency_key: str | None = None,
   ) -> SendResult: ...
   ```
   Sugar: `send_tx(...)` и `send_marketing(...)`.

2. **`TemplateRegistry`** — хранилище Jinja2-шаблонов с i18n:
   ```python
   registry.register(
       key="kyc_approved",
       templates={
           "ru": {"subject": "KYC одобрен", "body": "Здравствуйте, {{name}}!"},
           "en": {"subject": "KYC approved", "body": "Hello, {{name}}!"},
       },
       channels=["email", "sms"],
   )
   ```
   Autoescape enabled default (`select_autoescape(["html", "xml"])`) —
   защита от XSS при HTML-email.

3. **`PriorityRouter`** — tx-поток использует свой pool (большой min_size,
   строгий circuit), marketing — отдельный (eventually-consistent, меньше
   ресурсов). Реализация через `asyncio.Queue` per priority + worker
   coroutines.

4. **DLQ** — таблица `notification_dlq` (Alembic migration):
   ```
   id UUID PK
   channel VARCHAR
   template_key VARCHAR
   locale VARCHAR
   context JSONB
   recipient TEXT
   priority VARCHAR
   last_error TEXT
   attempts INT
   failed_at TIMESTAMPTZ
   ```
   После `retries_max` попыток сообщение уходит в DLQ. Streamlit page
   `27_Notifications_DLQ.py` показывает failed с кнопкой Replay.

5. **Adapters** — `NotificationChannel` Protocol:
   ```python
   class NotificationChannel(Protocol):
       kind: str
       async def send(self, recipient: str, subject: str, body: str,
                      metadata: dict[str, Any]) -> None: ...
       async def health(self) -> HealthResult: ...
   ```
   Реализации: email (существующий SMTP-pool), telegram (Bot API via httpx),
   slack (webhook + API), teams (webhook), express (BotX), webhook (HMAC).
   SMS — новый: МТС / МегаФон / SMS.ru через httpx с рантайм-выбором
   через `settings.sms.provider`.

### Что НЕ включено в IL2.2

- **Fallback chain провайдеров** (A → B → C при circuit_open) — deferred
  follow-up по решению пользователя в AskUserQuestion.
- **A/B testing шаблонов** — deferred (есть механика в PromptRegistry,
  можно переиспользовать позже).
- **Scheduling задержек** — уже есть `StreamClient.publish_to_*` с APScheduler;
  при необходимости gateway использует его.

## Последствия

### Положительные

- Единый API: `gateway.send(...)` — 1 строка вместо 5 в сервисах.
- Jinja2 + i18n — шаблоны версионируемы, легко добавлять локали.
- DLQ + replay — гарантии доставки для критичных сценариев (банковские tx).
- Priority queues — tx не блокируется marketing-пиками.
- Transport вынесен в infra — проще тесты (smoke без бизнес-логики),
  проще замена провайдера.

### Отрицательные

- Breaking: старые вызовы `notification_hub.send(...)` работают через shim,
  но `DeprecationWarning` напоминает о миграции.
- DLQ — ещё одна Postgres-таблица под мониторинг (risk: OOM при лавинах —
  решается rate-limit на DLQ-write + TTL 7 дней; см. Risk R4 в плане).
- Jinja2 vulnerabilities при user-controlled templates → сервисы не должны
  регистрировать templates от внешнего input (только из доверенных
  локализационных каталогов).

## Критерии DoD ADR-023

- [ ] ADR-023 создан в `docs/adr/`.
- [ ] `src/infrastructure/notifications/gateway.py` (фасад).
- [ ] `src/infrastructure/notifications/templates.py` (Jinja2 registry + i18n).
- [ ] `src/infrastructure/notifications/dlq.py` (replayer + model).
- [ ] `src/infrastructure/notifications/router.py` (priority queues).
- [ ] `src/infrastructure/notifications/adapters/*.py` — 7+ адаптеров.
- [ ] Alembic migration для `notification_dlq`.
- [ ] `src/services/ops/notification_hub.py` — deprecation shim.
- [ ] Streamlit page `27_Notifications_DLQ.py`.
- [ ] Smoke-тест: `gateway.send_tx(...)` рендерит+отправляет через mock-адаптер.

## Ссылки

- План: `/root/.claude/plans/tidy-jingling-map.md` (IL2.2).
- Референсы: MuleSoft Notification Connector docs; WSO2 Event-Sink chain with
  DLQ; TIBCO BW Notification Service.
