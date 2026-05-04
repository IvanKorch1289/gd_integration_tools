# ADR-040 — SecretsBackend через svcs (Wave A)

* **Статус:** Accepted (Wave A foundation, 2026-05-04)
* **Контекст:** GAP-анализ показал, что `EnvSecretsBackend`
  (`src/infrastructure/security/env_secrets.py`) не зарегистрирован в
  `svcs`-контейнере. Бизнес-код вынужден либо инстанцировать его руками,
  либо обращаться напрямую к `os.environ`, что мешает
  hot-swap (Vault) и тестам.
* **Решение:**
  1. Регистрация `SecretsBackend` (`src/core/interfaces/secrets.py`) как
     type-key в `svcs_registry` через factory в
     `src/plugins/composition/service_setup.py::register_secrets_backend`.
  2. Диспетчер по env-флагу `SECRETS_BACKEND`:
     * `env` (default) → `EnvSecretsBackend()`;
     * `vault` → `NotImplementedError("Wave K")` — сознательный stub,
       реальный `VaultSecretsBackend` создаётся в Wave K совместно с
       `docker-compose.prod.yml` и Vault-сервисом.
  3. Регистрация выполняется внутри `register_all_services()`, который
     вызывается в lifespan (`src/plugins/composition/lifecycle.py`).
* **Альтернативы:**
  * Прямой инстанс в каждом call-site — отверг как нарушение DI/Clean
    Architecture (composition root уходит в core).
  * Делать flag-based dispatch через config-validator — отверг ради
    минимальной поверхности изменений: одной env-переменной достаточно
    для prod-разделения.
* **Последствия:**
  * Любой сервис теперь получает backend через
    `container.get(SecretsBackend)`.
  * Wave K заполняет vault-ветку реальной реализацией (HVAC), не меняя
    точек вызова.
  * `core/interfaces/secrets.py` остаётся стабильным контрактом.
* **Связь:** ADR-002 (svcs DI), ADR-039 (notification gateway),
  будущий ADR Vault (Wave K).
