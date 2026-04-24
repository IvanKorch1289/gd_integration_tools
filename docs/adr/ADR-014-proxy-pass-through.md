# ADR-014 — Proxy pass-through как два DSL-процессора

## Status
Accepted (Wave 3.5)

## Context
Бизнес-сценарий: gd_integration_tools часто должен работать как
тонкий прокси — принять входящий запрос и переадресовать его во
внешний сервис без бизнес-логики. Примеры:

* проксирование платёжного API партнёра с обогащением header-ов
  (X-Tenant, X-Request-Id, strip Authorization);
* мост между внутренним Kafka-топиком и RabbitMQ exchange
  (``kafka:orders.in → rabbit:orders.out``);
* SOAP-passthrough с сохранением namespaces;
* gRPC-прокси с generic bytes-pipe.

Вариант «новый DSL-диалект с keyword-ами proxy / listen / forward»
красиво читается, но удваивает площадь поддержки: парсер, линтер,
сериализация, docs. Текущий DSL уже содержит все нужные инфраструктурные
куски — inbound адаптеры, outbound-клиенты, middleware, трассировку.

## Decision
Добавляем **два процессора** в существующий DSL без нового диалекта:

* ``ExposeProxyProcessor(src, methods?, header_policy?)`` — декларирует
  inbound-биндинг текущего роута.
* ``ForwardToProcessor(dst, pass_headers, header_policy, rewrite_path,
  timeout)`` — outbound pass-through.

И один builder-хелпер ``RouteBuilder.proxy(src, dst, **opts)`` как
sugar над ``expose_proxy → forward_to``.

Протоколы первой итерации: HTTP/REST, SOAP (XML body relay), gRPC
(generic bytes-pipe), queue-to-queue (Kafka/Rabbit/Redis через
``StreamClient``).

Трансформации: pure pass-through. Опциональная ``HeaderMapPolicy``
(``add / drop / override``) — минимум сюрпризов. Для полного
transformation pipeline пользователь пишет обычный Route без
``.proxy()``.

## Consequences

### Плюсы
* Нулевой рост площади DSL-поддержки (два процессора, одна обёртка).
* Всё инфраструктурное переиспользуется: ``StreamClient`` для очередей,
  ``httpx.AsyncClient`` для HTTP/SOAP, ``grpc.aio`` для gRPC.
* Автоматически доступны middleware и трассировка DSL.
* Легко углубить до transformation-режима — достаточно вставить
  обычные DSL-шаги между ``expose_proxy`` и ``forward_to``.

### Минусы
* Нет «самодокументирующегося» красивого DSL для чисто proxy-routes —
  читатель видит Python-код с fluent-chain, а не декларативный
  proxy-блок. Для типовых кейсов компенсируется ``RouteBuilder.proxy()``.
* Routing на входе (HTTP/SOAP/gRPC) пока должен регистрироваться
  в соответствующем entrypoint-слое. ``ExposeProxyProcessor`` только
  нормализует spec в Exchange, но не поднимает listen-сокет сам.

### Осознанные ограничения первой итерации
* Нет MTOM/WS-Security rewrite для SOAP.
* gRPC — только unary (без streaming).
* Нет TLS-termination на прокси (используется готовый ingress).
* Нет request/response-streaming для HTTP (копируется body).

Эти пункты намеренно вынесены — их можно поднять отдельным Wave,
когда появится реальный use-case.

## Alternatives considered

### A. Отдельный DSL-диалект (proxy/listen/forward keywords)
Читаемый, но дорогой: парсер + линтер + docs. Отвергнут из-за
пересечения функциональности с существующим DSL.

### B. Static YAML config без DSL-шагов
Подходит только для простых static rules (``src → dst``). Не
масштабируется на scheduled / header-rewrite / feature-flag
сценарии. Отвергнут как слишком узкий.

## References
* PLAN.md → Шаг 3.5.
* src/dsl/engine/processors/proxy/ — реализация.
* src/dsl/builder.py → методы ``expose_proxy``, ``forward_to``, ``proxy``.
