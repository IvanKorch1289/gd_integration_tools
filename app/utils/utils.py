import base64
import uuid
from datetime import datetime
from typing import Any, Type

import pandas as pd
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.schemas.base import BaseSchema
from app.utils.decorators.singleton import singleton
from app.utils.logging_service import app_logger


__all__ = (
    "utilities",
    "AsyncChunkIterator",
)


@singleton
class Utilities:
    """Utility class for common operations and external service integration.

    Provides methods for data conversion, protocol handling, async task execution,
    and various data formatting operations.
    """

    logger = app_logger

    def transfer_model_to_schema(
        self,
        instance: Any,
        schema: Type[BaseSchema],
        from_attributes: bool = False,
    ) -> BaseSchema:
        """Converts a model instance to Pydantic schema.

        Args:
            instance: Model instance to convert
            schema: Target Pydantic schema class
            from_attributes: Flag for ORM mode conversion

        Returns:
            BaseSchema: Initialized schema instance

        Raises:
            ValueError: If conversion fails
        """
        try:
            return schema.model_validate(
                instance, from_attributes=from_attributes
            )
        except Exception as exc:
            self.logger.error(f"Model to schema conversion error: {exc}")
            raise ValueError(
                f"Model to schema conversion error: {exc}"
            ) from exc

    async def encode_base64(self, data: Any) -> Any:
        """
        Encode non-ASCII values in any data structure to be ASCII-compatible using Base64.

        Args:
            data: Input data (str, dict, list, tuple, etc.)

        Returns:
            Encoded data with all strings converted to Base64
        """
        if isinstance(data, (str, bytes)):
            # Кодируем строку или байты в Base64
            if isinstance(data, str):
                data = data.encode("utf-8")
            return base64.b64encode(data).decode("ascii")
        elif isinstance(data, (dict, list, tuple)):
            if isinstance(data, dict):
                return {
                    key: await self.encode_base64(value)
                    for key, value in data.items()
                }
            elif isinstance(data, (list, tuple)):
                return [await self.encode_base64(item) for item in data]
        else:
            # Возвращаем данные как есть, если это не строка и не коллекция
            return data

    async def decode_base64(self, data: Any) -> Any:
        """
        Decode Base64-encoded values in any data structure back to original strings.

        Args:
            data: Input data (str, dict, list, tuple, etc.)

        Returns:
            Decoded data with all Base64 strings converted back to original strings
        """
        if isinstance(data, str):
            try:
                # Декодируем Base64 строку в байты
                decoded_bytes = base64.b64decode(data)
                # Пытаемся декодировать байты в строку UTF-8
                return decoded_bytes.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                # Если декодирование в строку не удалось, возвращаем байты
                return decoded_bytes
        elif isinstance(data, (dict, list, tuple)):
            # Рекурсивно обрабатываем вложенные структуры
            if isinstance(data, dict):
                return {
                    key: await self.decode_base64(value)
                    for key, value in data.items()
                }
            elif isinstance(data, (list, tuple)):
                return [await self.decode_base64(item) for item in data]
        else:
            # Возвращаем данные как есть, если это не строка и не коллекция
            return data

    async def decode_bytes(self, data: Any) -> Any:
        """
        Decode Redis data (bytes) into a usable format.

        Args:
            data: Input data from Redis (bytes, dict, list, etc.)

        Returns:
            Decoded data with all bytes converted to strings or appropriate types
        """
        if isinstance(data, bytes):
            # Декодируем байты в строку
            data = data.decode("utf-8")
        if isinstance(data, (dict, list, tuple)):
            # Рекурсивно обрабатываем вложенные структуры
            if isinstance(data, dict):
                return {
                    await self.decode_bytes(key): await self.decode_bytes(
                        value
                    )
                    for key, value in data.items()
                }
            elif isinstance(data, (list, tuple)):
                return [await self.decode_bytes(item) for item in data]
        else:
            # Возвращаем данные как есть, если это не байты и не коллекция
            return data

    def ensure_url_protocol(self, url: str) -> str:
        """Ensures URL contains valid protocol prefix.

        Args:
            url: Input URL string

        Returns:
            URL with protocol prefix
        """
        if not url.startswith(("http://", "https://")):
            return f"http://{url}"
        return url

    def generate_link_page(self, url: str, description: str) -> HTMLResponse:
        """Generates HTML page with clickable link.

        Args:
            url: Target URL
            description: Link description text

        Returns:
            HTMLResponse: Formatted HTML page
        """
        return HTMLResponse(
            f"""
            <html>
                <body>
                    <p>{description} link: <a href="{url}" target="_blank">{url}</a></p>
                </body>
            </html>
            """
        )

    def convert_numpy_types(self, value: Any) -> Any:
        """Converts numpy types to native Python types.

        Args:
            value: Input value with possible numpy types

        Returns:
            Value with converted types
        """
        if pd.api.types.is_integer(value):
            return int(value)
        if pd.api.types.is_float(value):
            return float(value)
        if pd.api.types.is_bool(value):
            return bool(value)
        return value

    def convert_data(self, obj):
        # Рекурсивно преобразуем модели Pydantic в словари
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        elif isinstance(obj, list):
            return [self.convert_data(item) for item in obj]
        else:
            return obj

    def custom_json_encoder(self, obj: Any) -> dict:
        """Custom JSON encoder for special types.

        Handles:
        - UUID serialization
        - datetime ISO formatting

        Raises:
            TypeError: For unsupported types
        """
        if isinstance(obj, uuid.UUID):
            return {"__uuid__": True, "value": str(obj)}
        if isinstance(obj, datetime):
            return {"__datetime__": True, "value": obj.isoformat()}
        if isinstance(obj, BaseModel):
            obj = obj.model_dump()
        raise TypeError(f"Unserializable type: {type(obj)}")

    def custom_json_decoder(self, dct: dict) -> Any:
        """Custom JSON decoder for special type handling."""
        if "__uuid__" in dct:
            return uuid.UUID(dct["value"])
        if "__datetime__" in dct:
            return datetime.fromisoformat(dct["value"])
        return dct


class AsyncChunkIterator:
    """Async iterator for sequential traversal of byte chunks"""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            result = self.chunks[self.index]
            self.index += 1
            return result
        except IndexError:
            raise StopAsyncIteration


utilities = Utilities()
