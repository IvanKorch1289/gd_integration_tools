#!/bin/bash

set -e

uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 &

flet run frontend &

echo "Приложения запущены!"

wait