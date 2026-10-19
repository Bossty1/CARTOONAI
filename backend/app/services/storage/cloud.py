"""Optional S3 and Google Cloud Storage backends (SDKs imported lazily)."""
from __future__ import annotations

import io
from typing import BinaryIO

from ...core.config import Settings
from ...core.errors import AppError, unsupported
from .base import Area, StorageProvider, StoredObject


class S3Storage(StorageProvider):
    name = "s3"
    supports_signed_urls = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None

    def _client_or_raise(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore import-not-found
        except ImportError as exc:
            raise unsupported(
                "STORAGE_SDK_MISSING",
                "boto3 is required for S3 storage. Install backend/requirements-cloud.txt.",
                {"sdk": "boto3", "reason": str(exc)},
            ) from exc
        if not self.settings.s3_bucket:
            raise unsupported("STORAGE_NOT_CONFIGURED", "S3_BUCKET is not configured.")
        self._client = boto3.client(
            "s3",
            region_name=self.settings.s3_region or None,
            endpoint_url=self.settings.s3_endpoint_url or None,
            aws_access_key_id=self.settings.s3_access_key_id or None,
            aws_secret_access_key=self.settings.s3_secret_access_key or None,
        )
        return self._client

    def ensure_ready(self) -> None:
        self._client_or_raise()

    def save(self, area: Area, key_name: str, data: bytes, mime_type: str) -> StoredObject:
        client = self._client_or_raise()
        key = f"{area}/{key_name}"
        client.put_object(Bucket=self.settings.s3_bucket, Key=key, Body=data, ContentType=mime_type)
        return StoredObject(key=key, provider=self.name, size_bytes=len(data), mime_type=mime_type)

    def open(self, key: str) -> BinaryIO:
        client = self._client_or_raise()
        try:
            response = client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        except Exception as exc:  # botocore ClientError and friends
            raise AppError("ASSET_FILE_MISSING", "The stored object could not be read.", 410, {"error": str(exc)})
        return io.BytesIO(response["Body"].read())

    def delete(self, key: str) -> None:
        client = self._client_or_raise()
        client.delete_object(Bucket=self.settings.s3_bucket, Key=key)

    def exists(self, key: str) -> bool:
        client = self._client_or_raise()
        try:
            client.head_object(Bucket=self.settings.s3_bucket, Key=key)
            return True
        except Exception:
            return False

    def signed_url(self, key: str, expires_seconds: int) -> str | None:
        client = self._client_or_raise()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )


class GCSStorage(StorageProvider):
    name = "gcs"
    supports_signed_urls = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bucket = None

    def _bucket_or_raise(self):
        if self._bucket is not None:
            return self._bucket
        try:
            from google.cloud import storage as gcs  # type: ignore import-not-found
        except ImportError as exc:
            raise unsupported(
                "STORAGE_SDK_MISSING",
                "google-cloud-storage is required for GCS storage. Install backend/requirements-cloud.txt.",
                {"sdk": "google-cloud-storage", "reason": str(exc)},
            ) from exc
        if not self.settings.gcs_bucket:
            raise unsupported("STORAGE_NOT_CONFIGURED", "GCS_BUCKET is not configured.")
        if self.settings.gcs_credentials_json:
            import json

            from google.oauth2 import service_account  # type: ignore import-not-found

            info = json.loads(self.settings.gcs_credentials_json)
            credentials = service_account.Credentials.from_service_account_info(info)
            client = gcs.Client(credentials=credentials)
        else:
            client = gcs.Client()
        self._bucket = client.bucket(self.settings.gcs_bucket)
        return self._bucket

    def ensure_ready(self) -> None:
        self._bucket_or_raise()

    def save(self, area: Area, key_name: str, data: bytes, mime_type: str) -> StoredObject:
        bucket = self._bucket_or_raise()
        key = f"{area}/{key_name}"
        blob = bucket.blob(key)
        blob.upload_from_string(data, content_type=mime_type)
        return StoredObject(key=key, provider=self.name, size_bytes=len(data), mime_type=mime_type)

    def open(self, key: str) -> BinaryIO:
        bucket = self._bucket_or_raise()
        blob = bucket.blob(key)
        if not blob.exists():
            raise AppError("ASSET_FILE_MISSING", "The stored object could not be read.", 410)
        return io.BytesIO(blob.download_as_bytes())

    def delete(self, key: str) -> None:
        bucket = self._bucket_or_raise()
        bucket.blob(key).delete()

    def exists(self, key: str) -> bool:
        bucket = self._bucket_or_raise()
        return bool(bucket.blob(key).exists())

    def signed_url(self, key: str, expires_seconds: int) -> str | None:
        from datetime import timedelta

        bucket = self._bucket_or_raise()
        return bucket.blob(key).generate_signed_url(version="v4", expiration=timedelta(seconds=expires_seconds))
