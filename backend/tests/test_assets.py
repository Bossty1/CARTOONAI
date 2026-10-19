"""Asset access control, previews, sharing and deletion."""
from conftest import noisy_png, png_bytes


def test_preview_variant_is_smaller_and_jpeg(client):
    original_asset = client.post(
        "/api/uploads",
        files={"file": ("large.png", noisy_png((1600, 1200)), "image/png")},
        data={"kind": "image"},
    ).json()["asset"]
    original = client.get(f"/api/assets/{original_asset['id']}/content")
    preview = client.get(f"/api/assets/{original_asset['id']}/content", params={"variant": "preview"})
    assert original.status_code == 200
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.content[:2] == b"\xff\xd8"
    assert len(preview.content) < len(original.content)

    import cv2
    import numpy as np

    decoded = cv2.imdecode(np.frombuffer(preview.content, np.uint8), cv2.IMREAD_COLOR)
    assert max(decoded.shape[:2]) <= 1400


def test_download_sets_content_disposition(client, uploaded):
    response = client.get(f"/api/assets/{uploaded['id']}/content", params={"download": "true"})
    assert response.headers["content-disposition"].startswith("attachment")


def test_unknown_asset_returns_404(client):
    response = client.get("/api/assets/nope/content")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_other_owners_cannot_read_an_asset(client, uploaded):
    response = client.get(f"/api/assets/{uploaded['id']}/content", headers={"X-Owner-Id": "someone-else"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ASSET_FORBIDDEN"


def test_assets_are_scoped_per_owner(client, uploaded):
    mine = client.get("/api/assets").json()
    theirs = client.get("/api/assets", headers={"X-Owner-Id": "someone-else"}).json()
    assert any(asset["id"] == uploaded["id"] for asset in mine)
    assert all(asset["id"] != uploaded["id"] for asset in theirs)


def test_asset_can_be_deleted(client, uploaded):
    assert client.delete(f"/api/assets/{uploaded['id']}").status_code == 204
    assert client.get(f"/api/assets/{uploaded['id']}").status_code == 404


def test_share_reports_that_localhost_is_not_shareable(client, uploaded):
    response = client.post(f"/api/assets/{uploaded['id']}/share")
    assert response.status_code == 200
    body = response.json()
    assert body["shareable"] is False
    assert body["url"] is None
    assert "PUBLIC_BASE_URL" in body["message"]


def test_share_of_unknown_asset_is_404(client):
    assert client.post("/api/assets/nope/share").status_code == 404


def test_assets_can_be_filtered_by_kind(client):
    upload = client.post(
        "/api/uploads", files={"file": ("filter.png", png_bytes(), "image/png")}, data={"kind": "image"}
    ).json()
    originals = client.get("/api/assets", params={"kind": "image_original", "limit": 5}).json()
    assert all(asset["kind"] == "image_original" for asset in originals)
    assert any(asset["id"] == upload["asset"]["id"] for asset in originals)
