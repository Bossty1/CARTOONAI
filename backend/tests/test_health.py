"""System endpoints: health, capabilities, styles and engines."""


def test_health_reports_status(client):
    payload = client.get("/api/health").json()
    assert payload["status"] in {"ok", "degraded"}
    assert payload["database"] == "ok"
    assert payload["storage_ok"] is True
    assert payload["storage_provider"] == "local"
    assert isinstance(payload["ffmpeg_available"], bool)


def test_capabilities_describes_engines_honestly(client):
    payload = client.get("/api/capabilities").json()
    assert payload["active_engine"] in {"classic", "onnx"}
    assert payload["classic_fallback_enabled"] is True
    assert isinstance(payload["ai_model_configured"], bool)
    if not payload["ai_model_configured"]:
        assert payload["ai_model_requirements"]
    assert payload["limits"]["max_image_upload_mb"] > 0


def test_styles_are_available_and_labelled(client):
    styles = client.get("/api/styles").json()
    ids = {style["id"] for style in styles}
    assert {"anime", "comic", "sketch"} <= ids
    for style in styles:
        assert style["engine"] in {"classic-filter", "onnx-model"}
        assert isinstance(style["is_ai"], bool)
        if style["engine"] == "classic-filter":
            assert style["is_ai"] is False


def test_engine_catalog_includes_requirements(client):
    engines = client.get("/api/engines").json()
    by_id = {engine["id"]: engine for engine in engines}
    assert by_id["classic"]["is_ai"] is False
    assert by_id["onnx"]["is_ai"] is True
    assert "CARTOON_ONNX_MODEL_PATH" in by_id["onnx"]["requires"]
