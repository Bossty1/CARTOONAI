import io
import os
import tempfile
import time
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="cartoon-ai-tests-"))
os.environ.update(
    {
        "STORAGE_ROOT": str(TEST_ROOT / "storage"),
        "ENVIRONMENT": "test",
        "ENABLE_RATE_LIMIT": "false",
        "LOG_LEVEL": "WARNING",
        "JOB_WORKERS": "2",
        "PUBLIC_BASE_URL": "http://localhost:8000",
        "SHARE_SECRET": "test-share-secret",
    }
)

from fastapi.testclient import TestClient  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.main import app  # noqa: E402


def _draw(size=(320, 240), offset=0):
    image = Image.new("RGB", size, (240, 230, 210))
    draw = ImageDraw.Draw(image)
    width, height = size
    horizontal = max(1, width // 2 - 10)
    vertical = max(1, height // 2 - 10)
    draw.rectangle((5, 5, 5 + horizontal, 5 + vertical), fill=(70, 130, 200))
    draw.rectangle((width // 2, height // 3, max(width // 2 + 1, width - 5), max(height // 3 + 1, height - 5)), fill=(200, 90, 80))
    draw.line((0, height - 1, width - 1, 0), fill=(25, 25, 25), width=1)
    return image


def png_bytes(size=(320, 240), offset=0, fmt="PNG"):
    buffer = io.BytesIO()
    _draw(size, offset).save(buffer, fmt)
    return buffer.getvalue()


def noisy_png(size=(256, 256), seed=7):
    """A photographic-looking image (gradient + noise) with many distinct colours."""
    rng = np.random.default_rng(seed)
    width, height = size
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)
    grid_x, grid_y = np.meshgrid(x, y)
    red = (grid_x * 200 + 30).astype(np.uint8)
    green = (grid_y * 180 + 40).astype(np.uint8)
    blue = ((1 - grid_x) * 160 + 50).astype(np.uint8)
    stack = np.dstack([red, green, blue]).astype(np.int16)
    stack += rng.integers(-25, 25, stack.shape, dtype=np.int16)
    array = np.clip(stack, 0, 255).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(array, "RGB").resize(size).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def uploaded(client):
    response = client.post(
        "/api/uploads",
        files={"file": ("sample.png", png_bytes(), "image/png")},
        data={"kind": "image"},
    )
    assert response.status_code == 201, response.text
    return response.json()["asset"]


@pytest.fixture
def sample_png():
    return png_bytes()


@pytest.fixture
def noisy_upload(client):
    response = client.post(
        "/api/uploads",
        files={"file": ("noise.png", noisy_png((640, 480)), "image/png")},
        data={"kind": "image"},
    )
    assert response.status_code == 201, response.text
    return response.json()["asset"]


def wait_for_job(client, job_id, timeout=30.0):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish in time: {job}")
