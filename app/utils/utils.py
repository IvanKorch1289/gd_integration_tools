import uuid
from datetime import datetime
from typing import Any, Type

import asyncio
import json_tricks
import pandas as pd
from fastapi import Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.schemas.base import BaseSchema
from app.utils.decorators.singleton import singleton


__all__ = ("utilities",)


@singleton
class Utilities:
    """Utility class for common operations and external service integration.

    Provides methods for data conversion, protocol handling, async task execution,
    and various data formatting operations.
    """

    async def transfer_model_to_schema(
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
            raise ValueError(
                f"Model to schema conversion error: {exc}"
            ) from exc

    async def get_response_body(self, response: Response) -> Any:
        """Extracts and deserializes response body.

        Args:
            response: HTTP response object

        Returns:
            Deserialized response content
        """
        body = response.body.decode("utf-8")
        return json_tricks.loads(
            body, extra_obj_pairs_hooks=[self.custom_json_decoder]
        )

    async def decode_redis_data(self, redis_data):
        decoded_data = {}

        for key, value in redis_data.items():
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            if isinstance(value, dict):
                value = await self.decode_redis_data(value)

            decoded_data[key] = value

        return decoded_data

    async def ensure_url_protocol(self, url: str) -> str:
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

    async def convert_numpy_types(self, value: Any) -> Any:
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
        elif isinstance(obj, dict):
            return {k: self.convert_data(v) for k, v in obj.items()}
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
        raise TypeError(f"Unserializable type: {type(obj)}")

    def custom_json_decoder(self, dct: dict) -> Any:
        """Custom JSON decoder for special type handling."""
        if "__uuid__" in dct:
            return uuid.UUID(dct["value"])
        if "__datetime__" in dct:
            return datetime.fromisoformat(dct["value"])
        return dct

    def execute_async_task(self, coroutine: Any) -> bytes:
        """Executes async tasks in synchronous context.

        Args:
            coroutine: Async coroutine to execute

        Returns:
            bytes: Serialized execution result
        """
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(coroutine)
            return json_tricks.dumps(
                result, extra_obj_encoders=[self.custom_json_encoder]
            ).encode()
        finally:
            if loop and loop.is_closed():
                loop.close()


utilities = Utilities()
