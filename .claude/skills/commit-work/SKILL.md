---
name: commit-work
description: Подготовить и выполнить commit только по явному указанию пользователя.
disable-model-invocation: true
user-invocable: true
allowed-tools: Bash(git status *) Bash(git diff *) Bash(git add *) Bash(git commit *)
---

# Commit Work

Подготовь commit для задачи: $ARGUMENTS

Правила:
1. Commit делать только если пользователь явно попросил.
2. Перед commit:
   - покажи, какие файлы войдут в commit;
   - напомни, какие проверки были выполнены;
   - убедись, что нет несогласованных побочных изменений.
3. Затем выполни commit.
4. После commit должен сработать автоматический пересчёт graphify.
5. Push не делать.