# ADR-017: Rust / PyO3 для hot-path в production

* Статус: accepted
* Дата: 2026-04-21
* Фазы: J1

## Контекст

Часть hot-path кода (парсинг ISO8583, контрольные суммы МФО-файлов,
сериализация crypto-сообщений) на Python занимает > 40 % CPU
приложения. Оптимизация на Python исчерпана.

## Решение

Критические функции реализуются как Rust-extension через `pyo3` +
`maturin`. Интеграция:

1. Отдельный подпакет `src/_rust_ext/` — исходники Rust, собирается в
   wheel.
2. CI matrix — сборка wheel для Linux x86_64 + ARM64.
3. Пакет поставляется как built-distribution, не требует Rust-toolchain
   на target-машине.
4. Fallback на Python-реализацию — если `_rust_ext` не установлен
   (для dev-установок без Rust).

## Альтернативы

- **Cython**: менее гибкий для сложных C-ABI, менее производителен.
- **C-extension напрямую**: сложнее поддерживать.

## Последствия

- CI добавляет `cibuildwheel` job.
- Docker-образ получает pre-built wheel, без Rust toolchain.
- На несовместимых платформах приложение использует Python-fallback
  (production запускается только на linux-x86_64/ARM64, OK).
