#!/bin/bash
set -e  # Останавливает выполнение при ошибке

# Выполняем миграции
echo "Running database migrations..."
poetry run alembic upgrade head

# Запускаем основной скрипт
echo "Starting application..."
exec ./start.sh