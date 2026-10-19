"""Project CRUD, cascades and nested listings."""
from conftest import png_bytes


def test_project_lifecycle(client):
    created = client.post("/api/projects", json={"name": "Cartoon of Grog", "description": "fun run"})
    assert created.status_code == 201
    project = created.json()
    assert project["status"] == "draft"
    assert project["owner"] == "local"

    listed = client.get("/api/projects").json()
    assert any(item["id"] == project["id"] for item in listed)

    fetched = client.get(f"/api/projects/{project['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Cartoon of Grog"

    patched = client.patch(f"/api/projects/{project['id']}", json={"status": "active", "name": "Renamed"})
    assert patched.json()["status"] == "active"
    assert patched.json()["name"] == "Renamed"

    deleted = client.delete(f"/api/projects/{project['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/projects/{project['id']}").status_code == 404


def test_unknown_project_returns_enveloped_error(client):
    response = client.get("/api/projects/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "PROJECT_NOT_FOUND"
    assert "message" in body["error"]


def test_project_assets_and_jobs_are_listed(client):
    project = client.post("/api/projects", json={"name": "Scoped"}).json()
    upload = client.post(
        "/api/uploads",
        files={"file": ("sample.png", png_bytes(), "image/png")},
        data={"kind": "image", "project_id": project["id"]},
    ).json()["asset"]
    job = client.post(
        "/api/cartoonize", json={"asset_id": upload["id"], "project_id": project["id"], "style": "anime"}
    ).json()

    assets = client.get(f"/api/projects/{project['id']}/assets").json()
    jobs = client.get(f"/api/projects/{project['id']}/jobs").json()
    videos = client.get(f"/api/projects/{project['id']}/videos").json()
    assert [item["id"] for item in assets] == [upload["id"]]
    assert [item["id"] for item in jobs] == [job["id"]]
    assert videos == []


def test_deleting_project_removes_its_assets(client):
    project = client.post("/api/projects", json={"name": "Disposable"}).json()
    asset = client.post(
        "/api/uploads",
        files={"file": ("sample.png", png_bytes(), "image/png")},
        data={"kind": "image", "project_id": project["id"]},
    ).json()["asset"]

    client.delete(f"/api/projects/{project['id']}")
    assert client.get(f"/api/assets/{asset['id']}").status_code == 404
    remaining = client.get("/api/assets").json()
    assert all(item["id"] != asset["id"] for item in remaining)


def test_project_validation_error_shape(client):
    response = client.post("/api/projects", json={"name": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
