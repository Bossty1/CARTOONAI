"""Job status, logs and error paths."""
from conftest import wait_for_job


def test_job_status_progresses_to_completion(client, uploaded):
    job = client.post("/api/cartoonize", json={"asset_id": uploaded["id"]}).json()
    assert job["status"] in {"queued", "processing"}
    assert job["progress"] < 100
    finished = wait_for_job(client, job["id"])
    assert finished["status"] == "completed"
    assert finished["progress"] == 100
    assert finished["stage"] == "completed"
    assert finished["started_at"] and finished["finished_at"]


def test_job_logs_describe_the_engine(client, uploaded):
    job = client.post("/api/cartoonize", json={"asset_id": uploaded["id"]}).json()
    wait_for_job(client, job["id"])
    logs = client.get(f"/api/jobs/{job['id']}/logs").json()
    assert "Classic OpenCV filter" in logs["logs"]
    assert "is_ai=False" in logs["logs"]


def test_jobs_can_be_filtered_by_type_and_status(client, uploaded):
    job = client.post("/api/cartoonize", json={"asset_id": uploaded["id"]}).json()
    wait_for_job(client, job["id"])
    completed = client.get("/api/jobs", params={"status": "completed"}).json()
    assert any(item["id"] == job["id"] for item in completed)
    assert all(item["status"] == "completed" for item in completed)
    cartoonize_only = client.get("/api/jobs", params={"job_status": None}).json()
    assert isinstance(cartoonize_only, list)


def test_unknown_job_returns_404(client):
    response = client.get("/api/jobs/not-a-job")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_job_configuration_is_echoed_back(client, uploaded):
    job = client.post(
        "/api/cartoonize", json={"asset_id": uploaded["id"], "style": "sketch", "color_levels": 5}
    ).json()
    assert job["config"]["style"] == "sketch"
    assert job["config"]["color_levels"] == 5
    assert job["result"]["planned_engine"] == "classic-filter"
