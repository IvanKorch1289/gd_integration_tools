# ADR-018: HTTP/3 (QUIC) support

* Статус: accepted
* Дата: 2026-04-21
* Фазы: J1

## Контекст

HTTP/2 уже стандартный (A4 / ADR-009). HTTP/3 (QUIC) улучшает latency
на unreliable networks (мобильный трафик, роуминг в регионах).

## Решение

1. Granian (F1) поддерживает HTTP/3 QUIC нативно (с flag `--http 3`).
2. Для outgoing httpx HTTP/3 — опция через
   `httpx-http3-plugin` (опциональный extra).
3. В prod-конфиге включение — через env `HTTP3_ENABLED=true`.
4. Поддержка HTTP/3 — progressive enhancement: если клиент/прокси не
   поддерживает, работает HTTP/2.

## Альтернативы

- Пропустить HTTP/3: допустимо, но лишаемся преимущества для mobile.

## Последствия

- Port 443/UDP в ingress.
- CDN/reverse-proxy (Cloudflare/Traefik 3) должен поддерживать QUIC.
