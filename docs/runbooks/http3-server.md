# Runbook — HTTP/3 + WebTransport opt-in (Sprint 8)

## Назначение

Параллельный HTTP/3 endpoint поверх QUIC (RFC 9000 + RFC 9114) на базе
[`aioquic`](https://github.com/aiortc/aioquic). Поднимается **рядом** с
основным granian/uvicorn — не заменяет их. Предполагаемые сценарии:

- A/B-сравнение latency HTTP/2 vs HTTP/3 на edge-клиентах;
- WebTransport (RFC 9220) для bidirectional streams в браузере без
  WebSocket-handshake;
- staging-канал для клиентов с фильтрующими L4-балансировщиками,
  у которых TCP head-of-line blocking зашкаливает.

## Установка

```bash
uv sync --extra http3
```

Extra включает только `aioquic>=1.1.0` — pure-Python QUIC stack
(зависит от `cryptography>=42`, уже в base).

## Конфигурация

| ENV | Default | Описание |
|---|---|---|
| `APP_HTTP3_ENABLED` | `false` | Включает запуск http3-сервера |
| `APP_HTTP3_PORT` | `8443` | UDP-порт (отдельный от TCP 8000) |
| `APP_HTTP3_CERTFILE` | `null` | PEM-сертификат, ALPN h3/h3-29 |
| `APP_HTTP3_KEYFILE` | `null` | PEM-приватный ключ |
| `APP_HTTP3_MAX_DATAGRAM_FRAME_SIZE` | `65536` | RFC 9297 datagram limit |
| `APP_HTTP3_IDLE_TIMEOUT` | `60.0` | QUIC idle timeout (сек) |

Для prod-стендов сертификаты выдаются через тот же CA, что и granian
(см. `infrastructure/secrets/vault_*`). Для локального теста:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout key.pem -out cert.pem -subj "/CN=localhost"
```

## Запуск

```bash
APP_HTTP3_CERTFILE=cert.pem \
APP_HTTP3_KEYFILE=key.pem \
python manage.py http3-serve
```

Сервер слушает `udp://0.0.0.0:8443`, использует ту же FastAPI-app, что и
основной granian. После запуска корректно реагирует на `Ctrl+C`
(QUIC `CONNECTION_CLOSE` всем активным клиентам).

## Проверка

`curl --http3 https://localhost:8443/health/live` (curl с собранным
ngtcp2/quiche) или `python -m aioquic.examples.http3_client https://localhost:8443/`.

## Известные ограничения

- Сервер не обновляет TLS-сертификаты на лету — рестарт после rotation.
- WebTransport handler — scaffolding (см. `_protocol.py` —
  `WebTransportStreamDataReceived` пока игнорируется). Полный pipeline в
  следующем этапе Sprint 8.
- 0-RTT replay-protection не настраивается из конфига (используется
  aioquic-default — отключён для server-mode).

## Операционные риски

- **DDoS amplification**: QUIC требует `SO_REUSEADDR`/`SO_REUSEPORT`,
  и UDP не имеет SYN-cookies. На prod-стендах HTTP/3 ставится **только
  за L7-балансировщик** с rate-limit (envoy / nginx-quic / haproxy 3.0+).
- **Firewall**: убедиться, что UDP/8443 разрешён двунаправленно.
- **MTU path discovery**: aioquic берёт 1200 byte default; для сетей
  с jumbo-frames можно поднять `max_datagram_frame_size`.

## Связанные ADR

- ADR R3.1 (Sprint 7): Blue/Green compose — HTTP/3 endpoint должен
  быть включён только в green-цикле, чтобы исключить L4-LB roll-back.
