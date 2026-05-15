# Runbook: обновление политики WAF (outbound proxy)

**Wave**: `[wave:s8/k1-security-runbooks]`
**Owner**: K1 Security/Net.
**Связано**: `core/net/outbound_http_client.py`,
`make check-waf-coverage`, V15 R-V15-5.

## Контекст

Все исходящие HTTP-вызовы с capability `net.outbound.<host>:external`
проходят через WAF-прокси. Это включает:

* RPA browser-automation (patchright targets);
* Cloud LLM (litellm/instructor);
* Внешние REST-API (DaData, БКИ, СМЭВ, ЦБ).

`:internal` исключения требуют ADR + audit-event.

## Когда запускать

* Добавлен новый external host в плагине → нужно whitelisting в WAF.
* Изменена rate-limit политика для категории (e.g., LLM cost-shield).
* Отзыв host'а после deprecation.

## Action / Trigger / Checklist

### Action

1. WAF policy хранится в `.security/waf-policy.yaml` (декларативно).
2. CI gate `make check-waf-coverage` валидирует, что каждая capability
   `net.outbound.<host>:external` в `extensions/*/plugin.toml` имеет
   соответствующее правило в `.security/waf-policy.yaml`.
3. Deploy WAF-конфига — отдельный пайплайн `.github/workflows/waf-deploy.yml`
   (запускается по push в master при изменении `.security/`).

### Trigger — добавить новый host

```yaml
# .security/waf-policy.yaml
hosts:
  - name: dadata.ru
    purpose: "ФИО/ИНН/адрес enrichment для credit_pipeline"
    rate_limit: "100 rps"
    timeout_ms: 5000
    methods: [GET, POST]
    allowed_paths:
      - "/suggestions/api/4_1/rs/suggest/*"
    audit_required: true
```

```bash
# 1. Локальная валидация:
make check-waf-coverage

# 2. PR с тегом [wave:waf-policy-update].
# 3. После merge — auto-deploy в WAF cluster.
```

### Trigger — отзыв host'а (deprecation)

```bash
# 1. Найти все capability-обращения:
grep -rn "net.outbound.<host>:external" extensions/

# 2. Удалить из plugin.toml плагинов.
# 3. Удалить из .security/waf-policy.yaml.
# 4. make check-waf-coverage должен оставаться зелёным.
# 5. После deploy WAF блокирует любые новые попытки.
```

### Checklist — после deploy

- [ ] WAF gate `make check-waf-coverage` зелёный в CI.
- [ ] SIEM не показывает `waf.blocked` events для legitimate traffic.
- [ ] Метрики `waf_request_total{host="<new>"}` растут (sanity).
- [ ] Уведомить consumer-команду в `#oncall-net`.

## Эскалация

WAF-блокирует legitimate траффик → P1:

1. Включить временный bypass: `kubectl set env deploy/waf
   BYPASS_HOST=<host> --duration=1h` (требует SRE-роли).
2. Создать инцидент `WAF-<id>`.
3. Откатить policy изменением до устранения root cause.

## Ссылки

* PLAN.md §V15 R-V15-5 (WAF strict policy).
* `core/net/outbound_http_client.py` — фасад.
* Memory `feedback_wave_s1_security` (capability-gate + WAF).
