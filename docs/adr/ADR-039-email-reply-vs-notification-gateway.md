# ADR-039: EmailReplyChannel vs NotificationGateway

- **Статус:** accepted
- **Дата:** 2026-05-01
- **Фаза:** Wave F.2 (W22 Invoker consolidation)
- **Автор:** core team

## Контекст

В кодовой базе сосуществуют две сущности, отвечающие за доставку email:

1. **`EmailReplyChannel`** (`src/infrastructure/messaging/invocation_replies/email.py`,
   W22 этап B) — реализация `InvocationReplyChannel` для Invoker.
   Принимает `InvocationResponse`, читает recipient из `response.metadata`,
   формирует subject/body и шлёт через `EmailAdapter` (SMTP-pool).
   Используется для режимов `ASYNC_API` / `DEFERRED` /
   `ASYNC_QUEUE`, когда клиент хочет получить результат письмом.
2. **`NotificationGateway`** (`src/infrastructure/notifications/gateway.py`,
   ADR-023) — высокоуровневый фасад уведомлений с шаблонами
   (`TemplateRegistry`), локализацией, `PriorityRouter`, DLQ и retry.
   Многоканальный: email / sms / slack / teams / telegram / webhook /
   express.

Текущая ситуация — два независимых SMTP-конвейера: Invoker отправляет
через `EmailAdapter` напрямую; бизнес-уведомления идут через Gateway.
Это даёт дублирование (два пула соединений, два места retry/DLQ, два
формата шаблонов) и расходится с архитектурой Wave F (Single Gateway
per backend).

В рамках Wave F.2 (W22 consolidation) нужно зафиксировать решение.

## Рассмотренные варианты

- **Вариант 1 — Оставить EmailReplyChannel и NotificationGateway
  независимыми.** Простая текущая ситуация. Минус — дублирование
  SMTP-кода и retry/DLQ, два набора шаблонов, нарушение Single Gateway.
- **Вариант 2 — Удалить EmailReplyChannel; Invoker использует
  NotificationGateway напрямую.** Минимизирует дублирование.
  Минус — ломает контракт `InvocationReplyChannel` (registry знает только
  `ReplyChannelKind.EMAIL` без шаблонов/priority); требует переписать
  registry и DSL email-режимов.
- **Вариант 3 — `EmailReplyChannel` остаётся как адаптер, но
  делегирует доставку в NotificationGateway** (`gateway.send_tx(channel="email", ...)`).
  Сохраняет API `InvocationReplyChannel` для Invoker, убирает
  дублирование SMTP/шаблонов/DLQ. Минус — небольшая обёртка, два
  слоя в стеке вызова.

## Решение

Принят **Вариант 3**.

**`EmailReplyChannel` сохраняется как тонкий adapter** поверх
`NotificationGateway`. В send():

1. Resolve recipient (как сейчас: `response.metadata.email` /
   `recipient_email` / `default_recipient`).
2. Сформировать `template_key="invocation_result"` (новый базовый
   шаблон) и context = серилизованный `InvocationResponse`
   (status / result / error / mode / invocation_id / metadata).
3. Делегировать `await NotificationGateway.instance().send_tx(
   channel="email", template_key="invocation_result", context=...,
   recipient=recipient, idempotency_key=invocation_id)`.

`EmailAdapter` напрямую из EmailReplyChannel **удаляется** — все email
идут через единый pool/router/DLQ Gateway.

Реализация миграции — отдельная подзадача Wave 2.5 (LoggingBackend +
NotificationGateway integration) или Wave 9.8 (Email RPA), не блокирует
F.2 — текущий EmailReplyChannel продолжает работать как было до
миграции.

## Последствия

- **Положительные:**
  - Один SMTP-pool, единые retry/DLQ, единые шаблоны.
  - Единый стиль уведомлений (Invoker reply ↔ бизнес-уведомления).
  - Соответствует Single Gateway правилу Wave F.
  - Idempotency-ключ — по `invocation_id`, исключает дубли при retry.
- **Отрицательные:**
  - Дополнительный слой (Invoker → Channel → Gateway → Adapter) при
    отправке. Латентность на ~миллисекунды (NotificationGateway
    in-process, без I/O оверхеда).
  - Шаблон `invocation_result` нужно зарегистрировать в TemplateRegistry
    (новая регистрация, единичная).
- **Нейтральные:**
  - Контракт `InvocationReplyChannel` не меняется (Invoker и DSL не
    трогаются).
  - Тесты EmailReplyChannel — переписать на mock NotificationGateway
    вместо mock EmailAdapter.

## Связанные ADR

- ADR-023 (NotificationGateway) — базис фасада уведомлений.
- ADR-038 (ActionDispatcher) — Single Gateway правило.
- ADR-031 (DSL durable workflows) — DEFERRED режим использует email
  reply channel.
