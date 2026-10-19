"""Storage provider interface shared by local and cloud backends."""
from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal

Area = Literal["uploads", "outputs", "temp", "renders"]


@dataclass(frozen=True)
class StoredObject:
    key: str
    provider: str
    size_bytes: int
    mime_type: str


class StorageProvider(abc.ABC):
    name: str = "base"
    supports_signed_urls: bool = False

    @abc.abstractmethod
    def ensure_ready(self) -> None:
        """Validate configuration and create containers/directories."""

    @abc.abstractmethod
    def save(self, area: Area, key_name: str, data: bytes, mime_type: str) -> StoredObject:
        """Persist bytes under a generated key and return the stored object."""

    @abc.abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Return a readable binary handle for a stored key."""

    @abc.abstractmethod
    def delete(self, key: str) -> None:
        """Delete a stored key. Missing keys are ignored."""

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        """Whether the key is present in this backend."""

    def local_path(self, key: str) -> Path | None:
        return None

    def signed_url(self, key: str, expires_seconds: int) -> str | None:
        return None
