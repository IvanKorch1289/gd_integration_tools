#!/bin/bash

# Завершение всех процессов, связанных с uvicorn
pkill -f uvicorn

# Завершение всех процессов, связанных с flet
pkill -f flet

# Завершение всех процессов, связанных с celery
pkill -f celery

# Завершение всех процессов, связанных с flet
pkill -f flet


echo "Все приложения закрыты."