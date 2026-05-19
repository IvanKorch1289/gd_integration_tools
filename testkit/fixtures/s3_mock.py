"""Pytest-фикстура: in-memory S3 mock через ``moto``.

Lazy-import moto (extra ``testkit``). Скип, если moto не установлен.
Используется в extension-тестах, которые работают с
:class:`~src.backend.infrastructure.storage.s3.S3Storage`.

Использование::

    from testkit.fixtures.s3_mock import s3_mock, s3_client

    def test_upload(s3_client):
        s3_client.create_bucket(Bucket="my-extension")
        s3_client.put_object(Bucket="my-extension", Key="k", Body=b"x")
        obj = s3_client.get_object(Bucket="my-extension", Key="k")
        assert obj["Body"].read() == b"x"
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

__all__ = ("s3_mock", "s3_client")


@pytest.fixture
def s3_mock() -> Iterator[Any]:
    """Активирует in-memory S3 backend (``moto.mock_aws``).

    Yields:
        Контекст-менеджер moto (открыт во время теста).
    """
    try:
        from moto import mock_aws  # noqa: PLC0415
    except ImportError:
        pytest.skip("moto не установлен (extra: testkit)")

    with mock_aws():
        yield


@pytest.fixture
def s3_client(s3_mock: Any) -> Any:
    """boto3 S3 client, привязанный к in-memory backend.

    Returns:
        ``boto3.client("s3", region_name="us-east-1")``.
    """
    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        pytest.skip("boto3 не установлен (extra: testkit)")

    return boto3.client(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
