#!/bin/bash

# Запустить FastAPI сервер
uvicorn backend.main:app --reload &

# Запустить Streamlit сервер
streamlit run frontend/main.py &

wait # Ждать завершения всех процессов