"""Cartoonization jobs: real output, honest labelling, clear failure modes."""
import cv2
import numpy as np
from conftest import png_bytes, wait_for_job


def _decode(response) -> np.ndarray:
    assert response.status_code == 200
    return cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)


def test_classic_engine_produces_a_real_cartoon_image(client, uploaded):
    job = client.post("/api/cartoonize", json={"asset_id": uploaded["id"], "style": "comic"}).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed", finished
    assert finished["progress"] == 100
    result = finished["result"]
    assert result["engine"] == "classic-filter"
    assert result["is_ai"] is False
    assert result["style"] == "comic"
    assert any("not ai-generated" in note.lower() for note in result["notes"])

    original = _decode(client.get(f"/api/assets/{uploaded['id']}/content"))
    stylized = _decode(client.get(f"/api/assets/{result['asset_id']}/content"))
    assert stylized.shape == original.shape
    difference = np.abs(stylized.astype(np.float32) - original.astype(np.float32)).mean()
    assert difference > 5, "the stylized image should differ clearly from the original"


def test_posterisation_reduces_distinct_colours(client, noisy_upload):
    job = client.post(
        "/api/cartoonize",
        json={"asset_id": noisy_upload["id"], "style": "comic", "color_levels": 6, "strength": 1.0},
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed", finished
    original = _decode(client.get(f"/api/assets/{noisy_upload['id']}/content"))
    stylized = _decode(client.get(f"/api/assets/{finished['result']['asset_id']}/content"))
    original_colors = len(np.unique(original.reshape(-1, 3), axis=0))
    stylized_colors = len(np.unique(stylized.reshape(-1, 3), axis=0))
    assert original_colors > 1000
    assert stylized_colors < original_colors, (original_colors, stylized_colors)


def test_every_style_runs(client, uploaded):
    for style in ("anime", "comic", "ink", "illustration", "sketch", "3d", "pastel"):
        job = client.post("/api/cartoonize", json={"asset_id": uploaded["id"], "style": style}).json()
        finished = wait_for_job(client, job["id"])
        assert finished["status"] == "completed", (style, finished)
        assert finished["result"]["style"] == style


def test_onnx_engine_requires_a_model_when_fallback_disabled(client, uploaded):
    response = client.post(
        "/api/cartoonize",
        json={"asset_id": uploaded["id"], "engine": "onnx", "allow_classic_fallback": False},
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "MODEL_NOT_CONFIGURED"
    assert "CARTOON_ONNX_MODEL_PATH" in error["details"]["requirements"]


def test_onnx_engine_falls_back_with_an_explicit_note(client, uploaded):
    response = client.post(
        "/api/cartoonize",
        json={"asset_id": uploaded["id"], "engine": "onnx", "allow_classic_fallback": True},
    )
    assert response.status_code == 202
    finished = wait_for_job(client, response.json()["id"])
    assert finished["status"] == "completed"
    assert finished["result"]["engine"] == "classic-filter"
    assert finished["result"]["is_ai"] is False
    assert finished["result"]["notes"]


def test_background_removal_is_refused_honestly(client, uploaded):
    response = client.post(
        "/api/cartoonize", json={"asset_id": uploaded["id"], "background": "remove"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BACKGROUND_REMOVAL_UNAVAILABLE"


def test_background_blur_is_labelled_as_a_vignette(client, uploaded):
    job = client.post(
        "/api/cartoonize", json={"asset_id": uploaded["id"], "background": "blur"}
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed"
    combined = " ".join(finished["result"]["notes"]).lower()
    assert "vignette" in combined
    assert "not segmentation-based" in combined


def test_unknown_asset_is_rejected(client):
    response = client.post("/api/cartoonize", json={"asset_id": "missing-asset"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_style_and_engine_are_validated(client, uploaded):
    response = client.post("/api/cartoonize", json={"asset_id": uploaded["id"], "style": "oil-painting"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_output_format_options(client, uploaded):
    job = client.post(
        "/api/cartoonize",
        json={"asset_id": uploaded["id"], "output_format": "png", "quality": 80, "strength": 1.0},
    ).json()
    finished = wait_for_job(client, job["id"])
    assert finished["result"]["mime_type"] == "image/png"
    content = client.get(f"/api/assets/{finished['result']['asset_id']}/content")
    assert content.headers["content-type"] == "image/png"
    assert content.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_downloading_the_original_returns_the_uploaded_bytes(client):
    upload = client.post(
        "/api/uploads", files={"file": ("round-trip.png", png_bytes(), "image/png")}, data={"kind": "image"}
    ).json()
    content = client.get(f"/api/assets/{upload['asset']['id']}/content")
    assert content.content == png_bytes()
