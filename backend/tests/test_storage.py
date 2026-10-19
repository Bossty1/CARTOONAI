"""Local storage adapter behaviour and safety."""
import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.storage import LocalStorage, get_storage


def _local() -> LocalStorage:
    storage = get_storage()
    assert isinstance(storage, LocalStorage)
    return storage


def test_save_open_exists_delete_round_trip():
    storage = _local()
    stored = storage.save("temp", "unit/round-trip.bin", b"payload-bytes", "application/octet-stream")
    assert stored.provider == "local"
    assert stored.size_bytes == len(b"payload-bytes")
    assert storage.exists(stored.key)
    with storage.open(stored.key) as handle:
        assert handle.read() == b"payload-bytes"
    assert storage.local_path(stored.key) is not None
    storage.delete(stored.key)
    assert not storage.exists(stored.key)


def test_keys_cannot_escape_the_storage_root():
    storage = _local()
    for bad_key in ("../outside.txt", "temp/../../outside.txt", "..\\windows-escape.txt"):
        with pytest.raises(AppError) as excinfo:
            storage.open(bad_key)
        assert excinfo.value.code == "INVALID_STORAGE_KEY"


def test_unknown_area_is_rejected():
    storage = _local()
    with pytest.raises(AppError) as excinfo:
        storage.save("elsewhere", "x.bin", b"data", "application/octet-stream")  # type: ignore[arg-type]
    assert excinfo.value.code == "INVALID_STORAGE_AREA"


def test_missing_file_returns_gone():
    storage = _local()
    with pytest.raises(AppError) as excinfo:
        storage.open("temp/definitely-missing.bin")
    assert excinfo.value.code == "ASSET_FILE_MISSING"
    assert excinfo.value.status_code == 410


def test_areas_are_created_under_the_configured_root():
    settings = get_settings()
    storage = _local()
    storage.ensure_ready()
    for area in settings.storage_areas:
        assert (settings.storage_root_path / area).is_dir()
