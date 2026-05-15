# Runbook: серверный pre-receive docstring gate

**Wave**: `[wave:s8/k1-pre-receive-docstring]`
**Назначение**: блокировать push коммитов без русскоязычного docstring у
новых публичных `def`/`class` в защищённых каталогах
(`src/backend/core/**`, `src/backend/dsl/engine/**`,
`src/backend/core/interfaces/**`) на стороне git-сервера —
защита от обхода локального `pre-push` через `git push --no-verify`.

## Установка

```bash
make install-pre-receive REMOTE=/srv/git/gd_integration_tools.git
```

Цель копирует `tools/git_hooks/pre-receive` в `hooks/pre-receive`
remote-копии и проставляет executable-бит. На git-сервере (или в
контейнере, исполняющем git-операции) задаётся env:

```bash
export GD_PROJECT_DIR=/opt/gd_integration_tools          # рабочая копия с tools/check_docstrings.py
export GD_PYTHON_BIN=/usr/bin/python3                    # опционально, дефолт = python3
```

## Поддерживаемые платформы

* **GitHub Enterprise Server** — hooks через server-side admin SSH.
* **GitLab Omnibus / Self-managed** — server hooks через
  `<gitaly-storage>/<repo>.git/custom_hooks/pre-receive` (или Push Rules
  при наличии Premium-лицензии).
* **Gitea** — admin → Settings → Hooks → pre-receive.
* **Любой bare-репозиторий** — прямая копия в `hooks/pre-receive`.

## Обход и allowlist

Обход через `git push --no-verify` **не работает** для `pre-receive`
(этот флаг влияет только на client-side hooks). Если файл должен быть
исключён из проверки (амнистия legacy-кода) — добавь его в:

```text
tools/checks/check_docstrings_allowlist.txt
```

Запушенный allowlist влияет на следующие проверки. Удалить запись из
allowlist можно только вместе с добавлением валидных docstring'ов на
все публичные `def`/`class` файла.

## Диагностика

Hook пишет диагностику в stderr (которая попадает в логи git-сервера и
показывается клиенту). При срабатывании gate сообщение содержит путь,
номер строки и квалифицированное имя символа, например:

```
[pre-receive] src/backend/core/foo.py:42:0 SomeClass.bar — отсутствует docstring
```

Если на сервере не установлен Python — hook завершится с понятной
ошибкой; в этом случае поправь `GD_PYTHON_BIN` или установи `python3`.

## Связанное

* Локальный pre-push: `.pre-commit-config.yaml` (этап `pre-push`).
* CI mirror: `.github/workflows/docs-required.yml` /
  `.gitlab-ci.yml::docstrings`.
* Чекер: `tools/check_docstrings.py` (`--strict` + `--files`).
