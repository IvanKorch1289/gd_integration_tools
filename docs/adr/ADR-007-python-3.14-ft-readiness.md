# ADR-007: Python 3.14 Free-Threading readiness

* Статус: accepted
* Дата: 2026-04-21
* Фазы: F1

## Контекст

Python 3.14 поддерживает опциональный free-threaded mode (PEP 703). Это
убирает GIL, но имеет caveat-ы: библиотеки с C-extension должны явно
объявить совместимость (`Py_mod_gil`).

## Решение

1. Требование к prod-зависимостям: audit на GIL-совместимость (creosote
   + ручная проверка C-ext). Несовместимые — pin-нуть на mainstream
   версии или заменить.
2. Benchmark-скрипт `bench/ft_compare.py` (scaffolding) сравнивает
   `python` vs `python3.14-ft` на наших workload-ах.
3. Решение «включать FT в prod» — отложено до появления стабильной
   матрицы совместимых зависимостей (не раньше Q3 2026).

## Альтернативы

- **Включить сразу**: рискованно — C-extensions могут падать.
- **Игнорировать FT**: отвергнуто, теряем прирост для CPU-bound RAG/PII.

## Последствия

- CI получает matrix-job `python3.14-ft` (как allow-failure сейчас).
- Инструкция для DevOps: включить FT можно флагом Granian
  `--blocking-threads` + env PYTHONGIL=0.
