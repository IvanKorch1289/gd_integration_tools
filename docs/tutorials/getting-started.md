# Tutorial — Getting Started

Цель: запустить локальный dev-инстанс gd_integration_tools и убедиться,
что health-check проходит.

## Что вы узнаете
- Как поднять окружение (`uv sync`, `dev_light`).
- Как проверить, что приложение готово к работе.
- Куда смотреть в первую очередь.

## Шаги

1. Установите Python 3.14:
   ```bash
   pyenv install 3.14.4 && pyenv local 3.14.4
   ```
2. Установите зависимости:
   ```bash
   make init       # uv sync --all-extras
   ```
3. Запустите dev-light профиль (sqlite, без Docker):
   ```bash
   make dev-light
   ```
4. Откройте `http://localhost:8000/api/v1/health/ready` — должен быть 200.

## Проверка
- `curl http://localhost:8000/api/v1/health/ready` → `{"status": "ok"}`.
- `make actions` показывает > 0 actions.

## Next steps
- [Build your first action](build-first-action.md)
- [Plugin development](plugin-development.md)
