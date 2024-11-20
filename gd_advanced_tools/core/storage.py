from contextlib import asynccontextmanager
from io import BytesIO
from typing import Union

from aiobotocore.response import StreamingBody
from aiobotocore.session import get_session
from aiohttp import ClientError

from gd_advanced_tools.core.settings import settings


class S3Service:
    def __init__(
        self,
        bucket_name: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
    ):
        self.bucket_name = bucket_name
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key

    @asynccontextmanager
    async def _create_s3_client(self):
        session = get_session()
        async with session.create_client(
            's3',
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key
        ) as client:
            yield client

    async def upload_file_object(
        self,
        key: str,
        content: Union[str, bytes]
    ) -> None:
        async with self._create_s3_client() as client:
            if isinstance(content, bytes):
                buffer = BytesIO(content)
            else:
                buffer = BytesIO(content.encode('utf-8'))
                
            return await client.put_object(Bucket=self.bucket_name, Key=key, Body=buffer)

    async def list_objects(self, prefix: str) -> list[str]:
        async with self._create_s3_client() as client:
            response = await client.list_objects_v2(Bucket=self.bucket_name,)
            storage_content: list[str] = []
            
            try:
                contents = response['Contents']
            except KeyError:
                return storage_content
            
            for item in contents:
                storage_content.append(item['Key'])
            
            return storage_content

    async def get_file_object(self, key: str) -> StreamingBody | None:
        async with self._create_s3_client() as client:
            try:
                file_obj = await client.get_object(
                    Bucket=self.bucket_name,
                    Key=key
                )
            except ClientError as ex:
                if ex.response['Error']['Code'] == 'NoSuchKey':
                    return None
                raise ex
            
            return file_obj['Body']

    async def delete_file_object(
        self,
        key: str
    ) -> None:
        async with self._create_s3_client() as client:
            return await client.delete_object(Bucket=self.bucket_name, Key=key)


def s3_bucket_service_factory() -> S3Service:
    return S3Service(
        bucket_name=settings.storage_settings.fs_bucket,
        endpoint=settings.storage_settings.fs_endpoint,
        access_key=settings.storage_settings.fs_access_key,
        secret_key=settings.storage_settings.fs_secret_key,
    )