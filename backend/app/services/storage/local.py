"""Local filesystem storage used for development and self-hosted deployments."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO

from ...core.config import Settings
from ...core.errors import AppError
from .base import Area, StorageProvider, StoredObject

AREA_DIRS = ("uploads", "outputs", "temp", "renders")


class LocalStorage(StorageProvider):
    name = "local"

    def __init__(self, root: Path, settings: Settings) -> None:
        self.root = root
        self.settings = settings

    def ensure_ready(self) -> None:
        for area in AREA_DIRS:
            (self.root / area).mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        clean = key.replace("\\", "/").strip("/")
        if not clean or clean.startswith("../") or ".." in clean.split("/"):
            raise AppError("INVALID_STORAGE_KEY", "The storage key is not valid.")
        candidate = (self.root / clean).resolve()
        root = self.root.resolve()
        if root not in candidate.parents and candidate != root:
            raise AppError("INVALID_STORAGE_KEY", "The storage key points outside of the storage root.")
        return candidate

    def save(self, area: Area, key_name: str, data: bytes, mime_type: str) -> StoredObject:
        if area not in AREA_DIRS:
            raise AppError("INVALID_STORAGE_AREA", f"Unknown storage area '{area}'.")
        target = self._resolve(f"{area}/{key_name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=target.parent, delete=False)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, target)
        return StoredObject(
            key=f"{area}/{key_name}",
            provider=self.name,
            size_bytes=len(data),
            mime_type=mime_type,
        )

    def open(self, key: str) -> BinaryIO:
        path = self._resolve(key)
        if not path.is_file():
            raise AppError("ASSET_FILE_MISSING", "The stored file no longer exists.", 410)
        return path.open("rb")

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.is_file():
            path.unlink()
        parent = path.parent
        root = self.root.resolve()
        if parent != root and parent.parent != root and not any(parent.iterdir()):
            shutil.rmtree(parent, ignore_errors=True)

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).is_file()
        except AppError:
            return False

    def local_path(self, key: str) -> Path | None:
        path = self._resolve(key)
        return path if path.is_file() else None
