# Политика skills

## Основной принцип
Повторяемые процедуры должны жить в skills, а не в длинных prompt'ах и не в раздутом CLAUDE.md.

## Обязательно
- Для планирования использовать skill `plan-execute`
- Для любой правки исходного кода (написание, изменение, отладка, рефакторинг, ревью) — skill `ub-mode` (https://github.com/unclebob/ub-mode): First Make it Work → Then Make it Right → Follow Practice
- Для самопроверки использовать skill `verify-change`
- Для завершения крупных этапов использовать skill `compact-session`
- Для commit использовать skill `commit-work`
- Для первичного входа в незнакомую область использовать skill `codebase-map`

## Формат skills
- Использовать только каталог `skills/<name>/SKILL.md`
- Не использовать устаревший плоский `.md`-формат skills в корне `skills/`

## Запрещено
- дублировать одну и ту же процедуру одновременно в command, rule и skill;
- держать много длинных workflow-инструкций в CLAUDE.md.