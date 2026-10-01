from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import boto3
from botocore.config import Config

from app.errors import ApiError
from app.settings import settings


class Storage:
    def __init__(self):
        if not settings.bucket_access_key or not settings.bucket_secret_key:
            raise ApiError(503, "STORAGE_UNAVAILABLE", "Private storage is not configured")
        self.bucket = settings.bucket_name
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.bucket_endpoint,
            aws_access_key_id=settings.bucket_access_key,
            aws_secret_access_key=settings.bucket_secret_key,
            config=Config(signature_version="s3v4"),
        )

    def upload(self, path: Path, key: str, mime_type: str) -> None:
        try:
            self.client.upload_file(
                str(path), self.bucket, key, ExtraArgs={"ContentType": mime_type}
            )
        except Exception as exc:
            raise ApiError(503, "STORAGE_UPLOAD_FAILED", "Upload storage is unavailable") from exc

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def download(self, key: str, path: Path) -> None:
        self.client.download_file(self.bucket, key, str(path))

    def list_objects(self) -> Iterator[tuple[str, datetime]]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket):
            for item in page.get("Contents", []):
                yield item["Key"], item["LastModified"]


@lru_cache
def get_storage() -> Storage:
    return Storage()
