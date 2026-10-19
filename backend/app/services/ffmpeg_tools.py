"""FFmpeg/FFprobe discovery and process helpers."""
from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..core.config import Settings, get_settings
from ..core.errors import AppError

INSTALL_INSTRUCTIONS: dict[str, str] = {
    "windows": "winget install Gyan.FFmpeg  (or: choco install ffmpeg)",
    "macos": "brew install ffmpeg",
    "linux": "sudo apt install ffmpeg",
    "docker": "The provided docker-compose image already includes FFmpeg.",
}

_version_cache: dict[str, str | None] = {}


def resolve_binary(name: str) -> str | None:
    if not name:
        return None
    candidate = Path(name).expanduser()
    if candidate.is_file():
        return str(candidate)
    return shutil.which(name)


def ffmpeg_path(settings: Settings | None = None) -> str | None:
    return resolve_binary((settings or get_settings()).ffmpeg_binary)


def ffprobe_path(settings: Settings | None = None) -> str | None:
    return resolve_binary((settings or get_settings()).ffprobe_binary)


def ffmpeg_available(settings: Settings | None = None) -> bool:
    return ffmpeg_path(settings) is not None


def ffmpeg_version(settings: Settings | None = None) -> str | None:
    binary = ffmpeg_path(settings)
    if binary is None:
        return None
    if binary in _version_cache:
        return _version_cache[binary]
    try:
        completed = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=20, check=False
        )
        first_line = (completed.stdout or "").splitlines()[0] if completed.stdout else None
    except (OSError, subprocess.SubprocessError):
        first_line = None
    _version_cache[binary] = first_line
    return first_line


def missing_ffmpeg_error() -> AppError:
    return AppError(
        "FFMPEG_MISSING",
        "FFmpeg is not installed or could not be found, so video rendering is unavailable on this machine.",
        status_code=503,
        details={
            "install": INSTALL_INSTRUCTIONS,
            "configure": "Set FFMPEG_BINARY to an absolute path if it is not on PATH.",
            "note": "Image upload, cartoonization and adjustments do not require FFmpeg.",
        },
    )


def require_ffmpeg(settings: Settings | None = None) -> str:
    binary = ffmpeg_path(settings)
    if binary is None:
        raise missing_ffmpeg_error()
    return binary


def probe_media(path: Path, settings: Settings | None = None) -> dict | None:
    binary = ffprobe_path(settings)
    if binary is None or not Path(path).is_file():
        return None
    try:
        completed = subprocess.run(
            [binary, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if completed.returncode != 0 or not completed.stdout:
            return None
        return json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def run_ffmpeg(
    args: list[str],
    settings: Settings | None = None,
    on_progress: Callable[[int, str], None] | None = None,
    total_duration: float | None = None,
) -> str:
    """Run FFmpeg, streaming -progress output; returns the trailing stderr text."""
    settings = settings or get_settings()
    binary = require_ffmpeg(settings)
    command = [binary, *args]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise missing_ffmpeg_error() from exc

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key in {"out_time_us", "out_time_ms"} and on_progress and total_duration:
            try:
                microseconds = int(value)
            except ValueError:
                continue
            seconds = microseconds / 1_000_000
            percent = int(min(99, max(0, (seconds / total_duration) * 100)))
            on_progress(percent, "rendering")
    stderr = process.communicate(timeout=settings.video_timeout_seconds)[1] if process.stderr else ""
    if process.returncode != 0:
        raise AppError(
            "FFMPEG_FAILED",
            "FFmpeg could not render the video.",
            status_code=500,
            details={"exit_code": process.returncode, "stderr_tail": (stderr or "")[-1500:]},
        )
    return stderr or ""
