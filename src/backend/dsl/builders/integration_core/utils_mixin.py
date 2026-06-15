from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class UtilsMixin:
    """utilities (scan_file/call_function/get_setting/validate_response/evaluate_rules/render_docx/render_xlsx) для IntegrationCoreMixin. S62 W3 extraction."""

    __slots__ = ()

    def scan_file(
        self,
        *,
        s3_key_from: str | None = None,
        data_property: str | None = None,
        on_threat: str = "fail",
        result_property: str = "antivirus_scan_result",
    ) -> RouteBuilder:
        """Сканировать файл AV-бэкендом (Wave 2.4)."""
        from src.backend.dsl.engine.processors.scan_file import ScanFileProcessor

        return self._add(  # type: ignore[attr-defined]
            ScanFileProcessor(
                s3_key_from=s3_key_from,
                data_property=data_property,
                on_threat=on_threat,
                result_property=result_property,
            )
        )

    def call_function(
        self,
        ref: str,
        *,
        payload_from: str = "body",
        result_property: str = "function_result",
        inject: list[str] | None = None,
    ) -> RouteBuilder:
        """Вызов Python-функции ``module:fn`` (R-V15-6, V21 security).

        Безопасность: module-whitelist через
        ``plugin.toml::call_function_modules`` + capability
        ``function.call.<module>`` + audit-log каждого вызова.
        См. :class:`CallFunctionProcessor`.

        Args:
            ref: ``module.path:fn_name``.
            payload_from: ``body`` | ``body.<field>`` | ``properties.<name>``.
            result_property: Имя property для результата.
        """
        from src.backend.dsl.engine.processors.function_call import (
            CallFunctionProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CallFunctionProcessor(
                ref=ref,
                payload_from=payload_from,
                result_property=result_property,
                inject=inject,
            )
        )

    def get_setting(
        self, path: str, *, to: str = "body.setting", default: Any = None
    ) -> RouteBuilder:
        """Чтение настройки из application config (R-V15-17).

        Capability ``settings.read.<scope>``. См. :class:`GetSettingProcessor`.

        Args:
            path: Точечный путь (``skb.api_url``, ``ai.openai.model``).
            to: ``body.<field>`` | ``properties.<name>``.
            default: Значение по умолчанию если путь отсутствует.
        """
        from src.backend.dsl.engine.processors.get_setting import GetSettingProcessor

        return self._add(  # type: ignore[attr-defined]
            GetSettingProcessor(path=path, to=to, default=default)
        )

    def validate_response(
        self,
        *,
        schema: type | str | None = None,
        on_error: str = "fail",
        source: str = "out_body",
    ) -> RouteBuilder:
        """Pydantic-валидация response_body (R-V15-18).

        См. :class:`ResponseValidatorProcessor`.

        Args:
            schema: Pydantic-модель (тип) или ``module:ClassName`` (str для
                YAML-loader).
            on_error: ``fail`` | ``dlq`` | ``warn``.
            source: ``out_body`` (default) | ``in_body``.
        """
        from src.backend.dsl.engine.processors.validate_response import (
            ResponseValidatorProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            ResponseValidatorProcessor(schema=schema, on_error=on_error, source=source)
        )

    def render_docx(
        self,
        *,
        template: str,
        context_from: str | None = None,
        output_to: str = "docx_path",
    ) -> RouteBuilder:
        """Рендерит шаблон ``.docx`` со встроенными плейсхолдерами ``{{key}}``.

        Wave: ``[wave:s5/doc-generation-dsl]``. Использует python-docx
        (уже в зависимостях), без добавления docxtpl.

        Args:
            template: Путь к шаблону ``.docx``.
            context_from: dotted-path в ``exchange.body`` к словарю
                подстановок. ``None`` — весь body.
            output_to: dotted-path для записи пути созданного файла.
        """
        from src.backend.dsl.engine.processors.documents import (
            RenderDocxParams,
            RenderDocxProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            RenderDocxProcessor(
                RenderDocxParams(
                    template=template, context_from=context_from, output_to=output_to
                )
            )
        )

    def render_xlsx(
        self,
        *,
        template: str | None = None,
        context_from: str | None = None,
        output_to: str = "xlsx_path",
        mode: str = "replace",
    ) -> RouteBuilder:
        """Рендерит ``.xlsx`` (``replace`` placeholders или ``append_table``).

        Wave: ``[wave:s5/doc-generation-dsl]``. Использует openpyxl
        (уже в зависимостях), без добавления xlsxwriter.

        Args:
            template: Путь к существующему ``.xlsx`` (``None`` — новая книга).
            context_from: dotted-path к данным (dict или list[dict]).
            output_to: dotted-path для пути результата.
            mode: ``replace`` — подстановка ``{{key}}``; ``append_table`` —
                добавление list[dict] как таблицы.
        """
        from src.backend.dsl.engine.processors.documents import (
            RenderXlsxParams,
            RenderXlsxProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            RenderXlsxProcessor(
                RenderXlsxParams(
                    template=template,
                    context_from=context_from,
                    output_to=output_to,
                    mode=mode,
                )
            )
        )

    def evaluate_rules(
        self,
        *,
        rules: list[Any],
        context_from: str | None = None,
        decision_to: str = "decision",
        default_decision: str = "NO_MATCH",
    ) -> RouteBuilder:
        """First-match-wins rule engine поверх SimpleEval.

        Wave: ``[wave:s8/rule-engine-scaffold]``. Безопасный
        синхронный evaluator (без import/exec/eval-доступа к dunder'ам).

        Args:
            rules: Список ``Rule`` или dict с полями ``name``/``expr``/``decision``.
            context_from: dotted-path к словарю переменных.
            decision_to: dotted-path для записи решения.
            default_decision: Значение, если ни одно правило не сработало.
        """
        from src.backend.dsl.engine.processors.rule_engine import (
            EvaluateRulesParams,
            EvaluateRulesProcessor,
            Rule,
        )

        normalized: list[Rule] = [
            r if isinstance(r, Rule) else Rule(**r) for r in rules
        ]
        return self._add(  # type: ignore[attr-defined]
            EvaluateRulesProcessor(
                EvaluateRulesParams(
                    rules=normalized,
                    context_from=context_from,
                    decision_to=decision_to,
                    default_decision=default_decision,
                )
            )
        )

    def jq_query(
        self,
        expr: str,
        *,
        to: str = "body.jq_result",
        mode: str = "all",
    ) -> RouteBuilder:
        """JMESPath query via jq processor.

        Args:
            expr: JMESPath expression (e.g. ``users[*].name``).
            to: Destination dotted-path.
            mode: ``all`` (list), ``first`` (single), ``scalar`` (value or None).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.jq_query",
            "JqProcessor",
            expr=expr,
            to=to,
            mode=mode,
        )

    def duckdb_query(
        self,
        sql: str,
        *,
        sources: dict[str, str] | None = None,
        persistent_path: str | None = None,
    ) -> RouteBuilder:
        """DuckDB analytical SQL over body + lookup tables.

        Args:
            sql: SQL query referencing ``body`` and ``sources.*`` aliases.
            sources: ``alias -> dotted_path_in_headers`` for lookup tables.
            persistent_path: Path to DuckDB file (None = in-memory).
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.duckdb_query",
            "DuckDbQueryProcessor",
            sql=sql,
            sources=sources,
            persistent_path=persistent_path,
        )

    def zip_archive(
        self,
        *,
        action: str = "create",
        files_from: str | None = None,
        archive_to: str = "body.archive_path",
        password: str | None = None,
    ) -> RouteBuilder:
        """Create/extract ZIP archives.

        Args:
            action: ``"create"`` or ``"extract"``.
            files_from: dotted-path to list of file paths.
            archive_to: Destination for archive path.
            password: Optional password for encrypted archives.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.zip_archive",
            "ZipArchiveProcessor",
            action=action,
            files_from=files_from,
            archive_to=archive_to,
            password=password,
        )

    def ingest_file(
        self,
        *,
        file_path: str | None = None,
        file_path_from: str | None = None,
        content_type: str | None = None,
        chunk_size: int = 1024,
    ) -> RouteBuilder:
        """Ingest file into exchange for processing.

        Args:
            file_path: Absolute path to file.
            file_path_from: dotted-path to read path from.
            content_type: MIME type (auto-detected if None).
            chunk_size: Read chunk size in bytes.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ingest_file",
            "IngestFileProcessor",
            file_path=file_path,
            file_path_from=file_path_from,
            content_type=content_type,
            chunk_size=chunk_size,
        )
