-- DLQ replay dedup Lua script (S13 K2 W6).
--
-- Атомарная проверка "уже реплейн?" + лок на replay.
-- KEYS[1] = "dlq:replay:lock:<message_id>"
-- KEYS[2] = "dlq:replay:done:<message_id>"
-- ARGV[1] = TTL в секундах для lock
-- ARGV[2] = TTL в секундах для done-маркера
--
-- Возвращает:
--   1  — лок взят, можно реплейнить
--   0  — уже реплейнили или лок занят
--   -1 — done-маркер существует (уже завершено)
--
-- Все KEYS должны быть в одном slot (hashtag в id обязателен).

if redis.call("EXISTS", KEYS[2]) == 1 then
  return -1
end

local lock_taken = redis.call("SET", KEYS[1], "1", "NX", "EX", ARGV[1])
if lock_taken then
  return 1
else
  return 0
end
