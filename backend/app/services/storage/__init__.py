"""Storage factory: picks the provider named by STORAGE_PROVIDER."""
from __future__ import annotations

from functools import lru_cache

from ...core.config import get_settings
from .base import Area, StorageProvider, StoredObject
from .cloud import GCSStorage, S3Storage
from .local import LocalStorage

__all__ = ["Area", "StorageProvider", "StoredObject", "LocalStorage", "S3Storage", "GCSStorage", "get_storage", "reset_storage"]


@lru_cache
def get_storage() -> StorageProvider:
    settings = get_settings()
    if settings.storage_provider == "s3":
        provider: StorageProvider = S3Storage(settings)
    elif settings.storage_provider == "gcs":
        provider = GCSStorage(settings)
    else:
        provider = LocalStorage(settings.storage_root_path, settings)
    provider.ensure_ready()
    return provider


def reset_storage() -> None:
    get_storage.cache_clear()
