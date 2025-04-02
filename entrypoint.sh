#!/bin/sh
set -e

# Выполняем миграции через виртуальное окружение
echo "Running database migrations..."
alembic upgrade head

# Запускаем основной скрипт
echo "Starting application..."
exec ./start.sh
