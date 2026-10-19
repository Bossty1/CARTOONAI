"""Video planning is pure logic; rendering needs FFmpeg (covered both ways)."""
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.services.ffmpeg_tools import ffmpeg_available
from app.services.video_service import (
    AudioPlan,
    build_audio_filter,
    build_render_plan,
    build_video_filter,
    effective_transition_duration,
    resolve_size,
)


def test_resolve_size_for_every_combination():
    assert resolve_size("720p", "16:9") == (1280, 720)
    assert resolve_size("1080p", "9:16") == (1080, 1920)
    assert resolve_size("480p", "1:1") == (480, 480)
    for resolution in ("480p", "720p", "1080p"):
        for aspect in ("16:9", "9:16", "1:1", "4:3", "3:4"):
            width, height = resolve_size(resolution, aspect)
            assert width % 2 == 0 and height % 2 == 0


def test_resolve_size_rejects_unknown_values():
    with pytest.raises(AppError) as excinfo:
        resolve_size("4320p", "21:9")
    assert excinfo.value.code == "UNSUPPORTED_VIDEO_SIZE"


def test_transition_is_clamped_for_short_frames():
    assert effective_transition_duration("fade", 1.5, [1.0, 1.0], 2) == 0.45
    assert effective_transition_duration("fade", 0.6, [4.0, 4.0], 2) == 0.6
    assert effective_transition_duration("none", 0.6, [4.0, 4.0], 2) == 0.0
    assert effective_transition_duration("fade", 0.6, [4.0], 1) == 0.0
    assert effective_transition_duration("fade", 0.6, [0.5, 0.5], 2) == 0.0


def test_single_frame_filter_has_no_transition():
    graph, label, duration = build_video_filter([3.0], ["zoom_in"], "fade", 0.6, (1280, 720), 24)
    assert label == "vout"
    assert duration == 3.0
    assert "zoompan" in graph
    assert "xfade" not in graph


def test_two_frame_filter_uses_xfade_with_offset():
    graph, label, duration = build_video_filter([4.0, 3.0], ["zoom_in", "zoom_out"], "fade", 0.6, (1280, 720), 24)
    assert label == "vout"
    assert "xfade=transition=fade:duration=0.600:offset=3.400" in graph
    assert duration == pytest.approx(6.4)


def test_three_frame_filter_chains_transitions():
    graph, label, duration = build_video_filter(
        [4.0, 4.0, 4.0], ["zoom_in", "pan_left", "none"], "wipeleft", 0.5, (1280, 720), 30
    )
    assert label == "vout"
    assert graph.count("xfade") == 2
    assert "[x1][v2]xfade" in graph
    assert duration == pytest.approx(11.0)


def test_transition_none_uses_concat():
    graph, _, duration = build_video_filter([2.0, 2.0], ["none", "none"], "none", 0.5, (720, 1280), 30)
    assert "concat=n=2:v=1:a=0[vout]" in graph
    assert duration == 4.0


def test_render_plan_args_and_notes(tmp_path):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    plan = build_render_plan(
        frame_paths=[first, second],
        durations=[3.0, 3.0],
        effects=["zoom_in", "none"],
        transition_type="fade",
        transition_duration=0.5,
        aspect_ratio="9:16",
        resolution="480p",
        fps=30,
        output_path=tmp_path / "out.mp4",
    )
    assert plan.width == 480 and plan.height == 854
    args = plan.args
    assert args[0] == "-y"
    assert args.count("-loop") == 2
    assert "libx264" in args
    assert "yuv420p" in args
    assert "+faststart" in args
    assert any("no audio track" in note.lower() for note in plan.notes)
    assert str(tmp_path / "out.mp4") == args[-1]


def test_render_plan_rejects_missing_frames(tmp_path):
    with pytest.raises(AppError) as excinfo:
        build_render_plan(
            frame_paths=[tmp_path / "missing.png"],
            durations=[3.0],
            effects=["none"],
            transition_type="none",
            transition_duration=0.0,
            aspect_ratio="16:9",
            resolution="720p",
            fps=24,
            output_path=tmp_path / "out.mp4",
        )
    assert excinfo.value.code == "FRAME_FILE_MISSING"


def test_audio_filter_includes_volume_fades_and_trim():
    audio = AudioPlan(path=Path("song.mp3"), volume=0.8, fade_in=1.0, fade_out=2.0, loop=True)
    chain = build_audio_filter(audio, input_index=2, total_duration=10.0)
    assert chain.startswith("[2:a]volume=0.800")
    assert "afade=t=in:st=0:d=1.000" in chain
    assert "afade=t=out:st=8.000:d=2.000" in chain
    assert "atrim=0:10.000" in chain
    assert chain.endswith("[aout]")
    assert "apad" not in chain

    looped_off = build_audio_filter(AudioPlan(path=Path("song.mp3"), loop=False), 1, 5.0)
    assert "apad" in looped_off


def test_video_endpoint_reflects_ffmpeg_availability(client, uploaded):
    response = client.post(
        "/api/videos",
        json={"frames": [{"asset_id": uploaded["id"], "duration_seconds": 2.0}], "resolution": "480p"},
    )
    if ffmpeg_available():
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["video"]["status"] == "queued"
        assert body["job"]["type"] == "video"
    else:
        assert response.status_code == 503
        error = response.json()["error"]
        assert error["code"] == "FFMPEG_MISSING"
        assert "windows" in error["details"]["install"]
        assert "Image upload" in error["details"]["note"]


def test_video_request_validation(client, uploaded):
    duplicate = client.post(
        "/api/videos",
        json={
            "frames": [
                {"asset_id": uploaded["id"], "duration_seconds": 2.0},
                {"asset_id": uploaded["id"], "duration_seconds": 2.0},
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_asset = client.post("/api/videos", json={"frames": [{"asset_id": "nope"}]})
    assert missing_asset.status_code in {404, 503}
