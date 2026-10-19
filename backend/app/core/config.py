"""Application configuration loaded from environment variables / .env files."""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_DIR / ".env"), str(PROJECT_ROOT / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Cartoon AI"
    environment: str = "development"
    api_prefix: str = "/api"
    version: str = "0.1.0"

    database_url: str = ""

    storage_provider: str = "local"
    storage_root: str = str(PROJECT_ROOT / "storage")
    public_base_url: str = "http://localhost:8000"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    max_image_upload_mb: int = 25
    max_audio_upload_mb: int = 50
    max_image_pixels: int = 40_000_000
    min_image_side: int = 32
    max_image_side: int = 8000

    allow_classic_fallback: bool = True
    cartoon_engine: str = "auto"
    cartoon_onnx_model_path: str = ""
    cartoon_onnx_input_size: int = 0
    cartoon_onnx_normalize: str = "minus_one_one"
    cartoon_onnx_provider: str = "cpu"

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    video_timeout_seconds: int = 900
    keep_render_temp_files: bool = False

    job_workers: int = 2
    job_retention_hours: int = 168
    asset_retention_days: int = 30
    share_link_ttl_hours: int = 168
    share_secret: str = "change-me-share-secret"

    rate_limit_per_minute: int = 60
    enable_rate_limit: bool = True

    require_auth: bool = False
    api_keys: str = ""
    default_owner: str = "local"

    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    gcs_bucket: str = ""
    gcs_credentials_json: str = ""

    log_level: str = "INFO"

    @field_validator("storage_provider")
    @classmethod
    def _check_provider(cls, value: str) -> str:
        allowed = {"local", "s3", "gcs"}
        if value.lower() not in allowed:
            raise ValueError(f"storage_provider must be one of {sorted(allowed)}")
        return value.lower()

    @property
    def storage_root_path(self) -> Path:
        return Path(self.storage_root).expanduser().resolve()

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.storage_root_path / "app.db"
        return f"sqlite:///{db_path.as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def api_key_set(self) -> set[str]:
        return {key.strip() for key in self.api_keys.split(",") if key.strip()}

    @property
    def upload_dir(self) -> Path:
        return self.storage_root_path / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.storage_root_path / "outputs"

    @property
    def temp_dir(self) -> Path:
        return self.storage_root_path / "temp"

    @property
    def render_dir(self) -> Path:
        return self.storage_root_path / "renders"

    @property
    def max_image_upload_bytes(self) -> int:
        return self.max_image_upload_mb * 1024 * 1024

    @property
    def max_audio_upload_bytes(self) -> int:
        return self.max_audio_upload_mb * 1024 * 1024

    @property
    def storage_areas(self) -> dict[str, Path]:
        return {
            "uploads": self.upload_dir,
            "outputs": self.output_dir,
            "temp": self.temp_dir,
            "renders": self.render_dir,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
