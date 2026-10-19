"""Upload validation: formats, limits and error envelope."""
from conftest import png_bytes


def test_accepts_png_jpeg_and_webp(client):
    cases = [
        ("photo.png", png_bytes(), "image/png", "image/png"),
        ("photo.jpg", png_bytes(fmt="JPEG"), "image/jpeg", "image/jpeg"),
        ("photo.webp", png_bytes(fmt="WEBP"), "image/webp", "image/webp"),
    ]
    for filename, payload, content_type, expected_mime in cases:
        response = client.post(
            "/api/uploads", files={"file": (filename, payload, content_type)}, data={"kind": "image"}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["is_image"] is True
        assert body["asset"]["mime_type"] == expected_mime
        assert body["asset"]["width"] == 320
        assert body["asset"]["height"] == 240
        assert body["details"]["preview_url"].endswith("/content?variant=preview")


def test_rejects_non_image_files(client):
    response = client.post(
        "/api/uploads", files={"file": ("notes.txt", b"just text", "text/plain")}, data={"kind": "image"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_IMAGE"


def test_rejects_empty_file(client):
    response = client.post("/api/uploads", files={"file": ("empty.png", b"", "image/png")}, data={"kind": "image"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_UPLOAD"


def test_rejects_images_below_minimum_size(client):
    response = client.post(
        "/api/uploads", files={"file": ("tiny.png", png_bytes(size=(16, 16)), "image/png")}, data={"kind": "image"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IMAGE_TOO_SMALL"


def test_rejects_unknown_upload_kind(client):
    response = client.post(
        "/api/uploads", files={"file": ("sample.png", png_bytes(), "image/png")}, data={"kind": "video"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_UPLOAD_KIND"


def test_upload_to_unknown_project_is_404(client):
    response = client.post(
        "/api/uploads",
        files={"file": ("sample.png", png_bytes(), "image/png")},
        data={"kind": "image", "project_id": "does-not-exist"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"


def test_audio_upload_is_stored_and_flagged(client):
    wav_header = b"RIFF$\x00\x00\x00WAVEfmt " + b"\x00" * 32
    response = client.post(
        "/api/uploads", files={"file": ("track.wav", wav_header, "audio/wav")}, data={"kind": "audio"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_image"] is False
    assert body["asset"]["kind"] == "audio"
    assert "FFmpeg" in body["details"]["note"]


def test_audio_rejects_unsupported_type(client):
    response = client.post(
        "/api/uploads", files={"file": ("clip.xyz", b"binary", "application/octet-stream")}, data={"kind": "audio"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_AUDIO_TYPE"
