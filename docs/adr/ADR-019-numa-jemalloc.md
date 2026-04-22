# ADR-019: NUMA affinity + jemalloc для memory-intensive workloads

* Статус: accepted
* Дата: 2026-04-21
* Фазы: J1

## Контекст

Крупные RAG/analytical workload-ы (тысячи TPS) используют > 16 ГБ
heap. glibc-malloc на multi-socket серверах демонстрирует заметную
фрагментацию; NUMA-binding улучшает latency на 10-20 %.

## Решение

1. **jemalloc** — через `LD_PRELOAD=libjemalloc.so.2` в prod
   entrypoint. Помечено в `docs/DEPLOYMENT.md`.
2. **NUMA affinity** — через systemd unit или docker `--cpuset-cpus`,
   `--cpuset-mems`. Granian auto-detects num CPUs и подстраивает workers.
3. Shared-memory для IPC между процессами Granian — через
   `multiprocessing.shared_memory` (stdlib).

## Альтернативы

- **mimalloc**: тоже хорошо, но jemalloc у нас testирован в staging.
- **glibc default**: не подходит для крупных heap.

## Последствия

- Dockerfile prod: `ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2`.
- Deployment checklist проверяет numa-availability.
