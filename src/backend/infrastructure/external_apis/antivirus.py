import mimetypes
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from src.core.config.settings import settings
from src.infrastructure.clients.transport.http import (
    HttpClient,
    get_http_client_dependency,
)
from src.infrastructure.external_apis.s3 import S3Service, get_s3_service_dependency

__all__ = (
    "AntivirusService",
    "VirusDetectedError",
    "UnknownAntivirusVerdictError",
    "get_antivirus_service",
    "get_antivirus_service_dependency",
)


class VirusDetectedError(Exception):
    """Файл не прошёл антивирусную проверку."""


class UnknownAntivirusVerdictError(Exception):
    """Не удалось определить вердикт антивируса."""


class AntivirusService:
    """
    Сервис антивирусной проверки файлов.

    Сценарии:
    - Проверка файла, уже лежащего в S3.
    - Проверка входящего файла и загрузка в S3 только после clean-вердикта.
    """

    def __init__(self, http_client: HttpClient, s3_service: S3Service):
        from src.infrastructure.external_apis.logging_service import request_logger

        self.http_client = http_client
        self.s3_service = s3_service
        self.logger = request_logger

    async def scan_s3_file(
        self, key: str, multipart_field_name: str | None = None
    ) -> dict[str, Any]:
        file_bytes = await self.s3_service.get_file_bytes(key)
        filename = await self.s3_service.get_original_filename(key) or key
        content_type = await self.s3_service.get_content_type(key)

        return await self.scan_bytes(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            multipart_field_name=multipart_field_name,
            file_key=key,
        )

    async def scan_and_upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str | None = None,
        multipart_field_name: str | None = None,
        key: str | None = None,
    ) -> dict[str, Any]:
        scan_result = await self.scan_bytes(
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            multipart_field_name=multipart_field_name,
        )

        is_clean = scan_result["is_clean"]
        if is_clean is not True:
            raise VirusDetectedError(f"Файл {filename} не прошёл антивирусную проверку")

        s3_key = key or str(uuid.uuid4())

        await self.s3_service.upload_file(
            key=s3_key,
            content=file_bytes,
            original_filename=filename,
            content_type=content_type,
            extra_metadata={"av-status": "clean"},
        )

        return {
            "uploaded": True,
            "key": s3_key,
            "filename": filename,
            "content_type": content_type,
            "scan_result": scan_result,
        }

    async def scan_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str | None = None,
        multipart_field_name: str | None = None,
        file_key: str | None = None,
    ) -> dict[str, Any]:
        resolved_content_type = self._resolve_content_type(
            filename=filename, content_type=content_type
        )
        resolved_field_name = (
            multipart_field_name or settings.antivirus.multipart_field_name or filename
        )

        response = await self.http_client.make_request(
            method="POST",
            url=settings.antivirus.build_url("SCAN_FILE"),
            headers=settings.antivirus.default_headers,
            files={
                resolved_field_name: {
                    "content": file_bytes,
                    "filename": filename,
                    "content_type": resolved_content_type,
                }
            },
            response_type=settings.antivirus.response_type,
            raise_for_status=settings.antivirus.raise_for_status,
            connect_timeout=settings.antivirus.connect_timeout,
            read_timeout=settings.antivirus.read_timeout,
            total_timeout=settings.antivirus.total_timeout,
        )

        is_clean = self._extract_clean_flag(response["data"])

        result = {
            "file_key": file_key,
            "filename": filename,
            "content_type": resolved_content_type,
            "multipart_field_name": resolved_field_name,
            "status_code": response["status_code"],
            "response": response["data"],
            "response_headers": response["headers"],
            "is_clean": is_clean,
        }

        self.logger.info(
            "Антивирусная проверка выполнена",
            extra={
                "file_key": file_key,
                "filename": filename,
                "is_clean": is_clean,
                "status_code": response["status_code"],
            },
        )

        return result

    def _resolve_content_type(self, filename: str, content_type: str | None) -> str:
        if content_type:
            return content_type

        guessed_content_type, _ = mimetypes.guess_type(filename)
        return guessed_content_type or settings.antivirus.default_content_type

    def _extract_clean_flag(self, response_data: Any) -> bool:
        """
        Адаптер вердикта антивируса.

        Подстрой под фактический ответ вашего AV API.
        Сейчас обрабатывает наиболее типичные случаи:
        - {"is_clean": true}
        - {"infected": false}
        - {"status": "clean"} / {"verdict": "infected"}
        - "OK", "CLEAN", "INFECTED"
        """

        if isinstance(response_data, dict):
            if isinstance(response_data.get("is_clean"), bool):
                return response_data["is_clean"]

            if isinstance(response_data.get("infected"), bool):
                return not response_data["infected"]

            for key in ("status", "verdict", "result"):
                value = response_data.get(key)
                if isinstance(value, str):
                    normalized = value.strip().lower()
                    if normalized in {"clean", "ok", "safe", "passed", "no_virus"}:
                        return True
                    if normalized in {
                        "infected",
                        "virus",
                        "malicious",
                        "failed",
                        "threat",
                    }:
                        return False

        if isinstance(response_data, str):
            normalized = response_data.strip().lower()
            if normalized in {"clean", "ok", "safe", "passed", "no_virus"}:
                return True
            if normalized in {"infected", "virus", "malicious", "failed", "threat"}:
                return False

        raise UnknownAntivirusVerdictError(
            "Не удалось определить вердикт антивируса. "
            "Нужно адаптировать _extract_clean_flag() "
            "под фактический ответ внешнего API."
        )


@asynccontextmanager
async def get_antivirus_service() -> AsyncGenerator[AntivirusService, None]:
    service = AntivirusService(
        http_client=get_http_client_dependency(), s3_service=get_s3_service_dependency()
    )
    try:
        yield service
    finally:
        pass


_antivirus_service_dependency_instance: AntivirusService | None = None


def get_antivirus_service_dependency() -> AntivirusService:
    global _antivirus_service_dependency_instance
    if _antivirus_service_dependency_instance is None:
        _antivirus_service_dependency_instance = AntivirusService(
            http_client=get_http_client_dependency(),
            s3_service=get_s3_service_dependency(),
        )
    return _antivirus_service_dependency_instance
