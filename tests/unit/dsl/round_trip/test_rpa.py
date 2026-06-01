"""W30 — Round-trip тесты для RPA-процессоров.

Покрывает primitive-args batch (21 процессор):

* rpa.py (16): pdf_read / pdf_merge / word_read / word_write / excel_read /
  file_move / archive / ocr / image_resize / regex / render_template /
  hash / encrypt / decrypt / shell / email.
* rpa_banking.py (5): citrix / terminal_3270 / appium_mobile /
  email_driven / keystroke_replay.

Все builder-методы существовали до W30 — добавлен только ``to_spec()``.

Замечания по контракту:

* ``ShellExecProcessor.timeout_seconds`` не экспонируется через builder
  (`shell(...)`), поэтому при write-back теряется (default 30.0с).
* ``ShellExecProcessor.allowed_commands`` хранится как ``set`` —
  ``to_spec`` отдаёт ``sorted(list(...))`` для детерминизма.
* ``encrypt`` / ``decrypt`` сохраняют ключ как literal в YAML — для
  production нужны SecretRef-маркеры (см. W28 секрет-note в audit.md).
"""

# ruff: noqa: S101, S106

from __future__ import annotations

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        # ── rpa.py ──
        ("pdf_read", {}),
        ("pdf_read", {"extract_tables": True}),
        ("pdf_merge", {}),
        ("word_read", {}),
        ("word_write", {}),
        ("excel_read", {}),
        ("excel_read", {"sheet_name": "Sheet1"}),
        ("file_move", {}),
        ("file_move", {"src": "/a", "dst": "/b"}),
        ("file_move", {"src": "/a", "dst": "/b", "mode": "move"}),
        ("file_move", {"mode": "rename"}),
        ("archive", {}),
        ("archive", {"mode": "create"}),
        ("archive", {"mode": "extract", "format": "tar"}),
        ("ocr", {}),
        ("ocr", {"lang": "eng"}),
        ("image_resize", {}),
        ("image_resize", {"width": 800}),
        ("image_resize", {"width": 1024, "height": 768, "output_format": "JPEG"}),
        ("regex", {"pattern": r"\d+"}),
        ("regex", {"pattern": r"[a-z]+", "action": "replace", "replacement": "X"}),
        ("regex", {"pattern": r"^test$", "action": "match"}),
        ("render_template", {"template": "Hello, {{ name }}!"}),
        ("hash", {}),
        ("hash", {"algorithm": "md5"}),
        ("hash", {"algorithm": "sha512"}),
        ("encrypt", {"key": "FERNET_KEY_32B"}),
        ("decrypt", {"key": "FERNET_KEY_32B"}),
        ("shell", {"command": "ls"}),
        ("shell", {"command": "ls", "args": ["-la", "/data"]}),
        (
            "shell",
            {
                "command": "cat",
                "args": ["/etc/hosts"],
                "allowed_commands": ["cat", "ls", "wc"],
            },
        ),
        (
            "email",
            {
                "to": "user@example.com",
                "subject": "Hi",
                "body_template": "Hello {name}",
            },
        ),
        # ── rpa_banking.py ──
        ("citrix", {"operation": "launch", "session_id": "sess-1"}),
        ("citrix", {"operation": "click", "session_id": "sess-2"}),
        ("terminal_3270", {"host": "mainframe.local"}),
        ("terminal_3270", {"host": "mf.local", "port": 992, "action": "submit"}),
        (
            "appium_mobile",
            {"platform": "android", "app_package": "com.bank.app", "operation": "tap"},
        ),
        (
            "appium_mobile",
            {"platform": "ios", "app_package": "com.bank.ios", "operation": "input"},
        ),
        ("email_driven", {}),
        (
            "email_driven",
            {
                "mailbox": "Bank",
                "subject_filter": "statement",
                "extract": "csv_attachment",
            },
        ),
        ("keystroke_replay", {"script_name": "login_seq"}),
    ],
)
def test_w30_processor_round_trip(method: str, kwargs: dict) -> None:
    """Single-processor round-trip: builder → YAML → builder."""
    builder = RouteBuilder.from_(f"rt.w30.{method}", source="test:rt.w30")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, (
        f"Round-trip mismatch for {method}({kwargs}): {original} != {rebuilt}"
    )


def test_w30_document_pipeline_full_chain() -> None:
    """Реалистичный document-processing pipeline."""
    builder = (
        RouteBuilder.from_("rt.w30.docs", source="test:rt.w30.docs")
        .pdf_read(extract_tables=True)
        .regex(pattern=r"\b\d{10}\b", action="extract")
        .hash(algorithm="sha256")
        .render_template(template="Result: {{ body }}")
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    methods = [next(iter(p)) for p in original["processors"]]
    assert methods == ["pdf_read", "regex", "hash", "render_template"]


def test_w30_rpa_pipeline_full_chain() -> None:
    """Реалистичный RPA-pipeline: email → terminal → Citrix → keystroke."""
    builder = (
        RouteBuilder.from_("rt.w30.rpa.full", source="test:rt.w30.rpa.full")
        .email_driven(mailbox="Outbox", extract="pdf_attachment")
        .terminal_3270(host="mf.local", action="submit")
        .citrix(operation="screenshot", session_id="audit-1")
        .keystroke_replay(script_name="finalize")
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    methods = [next(iter(p)) for p in original["processors"]]
    assert methods == ["email_driven", "terminal_3270", "citrix", "keystroke_replay"]


def test_shell_allowed_commands_emitted_sorted() -> None:
    """``shell.allowed_commands`` хранится как set — to_spec отдаёт sorted list."""
    builder = RouteBuilder.from_("rt.shell", source="test:rt").shell(
        command="ls", allowed_commands=["wc", "cat", "ls"]
    )
    spec = builder.build().to_dict()
    proc = spec["processors"][0]
    assert proc == {"shell": {"command": "ls", "allowed_commands": ["cat", "ls", "wc"]}}


def test_pdf_merge_no_args() -> None:
    """``pdf_merge()`` — empty params dict."""
    builder = RouteBuilder.from_("rt.pdf", source="test:rt").pdf_merge()
    spec = builder.build().to_dict()
    assert spec["processors"][0] == {"pdf_merge": {}}


def test_image_resize_format_uppercased() -> None:
    """``image_resize`` нормализует output_format к UPPERCASE."""
    builder = RouteBuilder.from_("rt.img", source="test:rt").image_resize(
        width=100, output_format="jpeg"
    )
    spec = builder.build().to_dict()
    proc = spec["processors"][0]
    assert proc == {"image_resize": {"width": 100, "output_format": "JPEG"}}
