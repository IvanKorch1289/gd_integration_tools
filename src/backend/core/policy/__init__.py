"""PII fail-CLOSED policy package (cycle-4/D-AUDIT-109).

Централизованный fail-CLOSED contract для всех PII processing paths.
Заменил ранее fail-OPEN поведение (silent return raw PII при sanitizer
exception) на raise + audit + DLQ enqueue.
"""