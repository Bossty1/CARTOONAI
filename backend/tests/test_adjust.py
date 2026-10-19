"""Image adjustment jobs: geometry, exposure and failure handling."""
import cv2
import numpy as np
from conftest import wait_for_job


def _decode(response) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)


def test_brightness_and_contrast_change_pixels(client, uploaded):
    job = client.post(
        "/api/images/adjust",
        json={"asset_id": uploaded["id"], "adjustments": {"brightness": 1.4, "contrast": 1.2}},
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed", finished
    original = _decode(client.get(f"/api/assets/{uploaded['id']}/content"))
    adjusted = _decode(client.get(f"/api/assets/{finished['result']['asset_id']}/content"))
    assert adjusted.mean() > original.mean()


def test_crop_to_aspect_ratio_and_resize(client, uploaded):
    job = client.post(
        "/api/images/adjust",
        json={
            "asset_id": uploaded["id"],
            "adjustments": {"crop": {"aspect_ratio": "1:1"}, "width": 300, "output_format": "webp", "quality": 85},
        },
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed", finished
    assert finished["result"]["width"] == 300
    assert finished["result"]["height"] == 300
    assert finished["result"]["mime_type"] == "image/webp"


def test_explicit_crop_region(client, uploaded):
    job = client.post(
        "/api/images/adjust",
        json={"asset_id": uploaded["id"], "adjustments": {"crop": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 0.5}}},
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed", finished
    assert finished["result"]["width"] == 160
    assert finished["result"]["height"] == 120


def test_denoise_and_enhance_run(client, uploaded):
    job = client.post(
        "/api/images/adjust",
        json={"asset_id": uploaded["id"], "adjustments": {"denoise": 0.5, "enhance": True, "saturation": 1.3, "sharpness": 1.0}},
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed", finished


def test_invalid_crop_fails_the_job_with_a_clear_code(client, uploaded):
    job = client.post(
        "/api/images/adjust",
        json={"asset_id": uploaded["id"], "adjustments": {"crop": {"x": 0.0, "y": 0.0, "width": 0.01, "height": 0.01}}},
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "failed"
    assert finished["error_code"] == "INVALID_CROP"
    assert finished["error_message"]


def test_adjustment_bounds_are_validated(client, uploaded):
    response = client.post(
        "/api/images/adjust", json={"asset_id": uploaded["id"], "adjustments": {"brightness": 9.0}}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
