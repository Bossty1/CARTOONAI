"""Job handlers for cartoonization, adjustments and video rendering."""
from __future__ import annotations

import uuid
from pathlib import Path

from ..models import Asset, Video, new_id
from ..schemas import AdjustRequest, CartoonizeRequest, VideoCreateRequest
from ..services import image_service
from ..services.cartoon import StylizeOptions, resolve_engine
from ..services.ffmpeg_tools import ffmpeg_available, missing_ffmpeg_error
from ..services.storage import get_storage
from ..services.video_service import AudioPlan, build_render_plan, render_video
from .jobs import JobContext


def _asset_key(ctx: JobContext, extension: str) -> str:
    folder = ctx.project_id or "unassigned"
    return f"{folder}/{ctx.id}-{uuid.uuid4().hex[:8]}.{extension}"


def _store_output(ctx: JobContext, data: bytes, mime: str, extension: str, kind: str, extra: dict) -> Asset:
    storage = get_storage()
    stored = storage.save("outputs", _asset_key(ctx, extension), data, mime)
    asset = Asset(
        project_id=ctx.project_id,
        owner=ctx.owner,
        kind=kind,
        filename=f"{ctx.id}.{extension}",
        mime_type=mime,
        size_bytes=stored.size_bytes,
        provider=stored.provider,
        storage_key=stored.key,
        extra=extra,
    )
    ctx.session.add(asset)
    ctx.session.commit()
    ctx.session.refresh(asset)
    return asset


def _dimensions(image) -> tuple[int, int]:
    height, width = image.shape[:2]
    return int(width), int(height)


def run_cartoonize(ctx: JobContext) -> None:
    request = CartoonizeRequest.model_validate(ctx.config)
    storage = get_storage()
    ctx.update(5, "loading source image")
    source = ctx.fetch_asset(request.asset_id, allowed_kinds=("image_original", "image_processed"))
    data = storage.open(source.storage_key).read()
    image = image_service.decode_bgr(data)
    ctx.log(f"Loaded source asset {source.id} ({image.shape[1]}x{image.shape[0]}).")

    engine, meta = resolve_engine(request.engine, request.allow_classic_fallback)
    ctx.log(f"Engine: {engine.info.label} (is_ai={engine.info.is_ai}).")
    ctx.update(20, "stylizing")
    stylized = engine.stylize(
        image,
        StylizeOptions(
            style=request.style,
            strength=request.strength,
            edge_strength=request.edge_strength,
            color_levels=request.color_levels,
            smooth_iterations=request.smooth_iterations,
        ),
    )
    notes = [str(meta.get("note"))] if meta.get("note") else []
    stylized, background_note = image_service.apply_background(stylized, request.background)
    if request.background != "keep":
        notes.append(background_note)

    ctx.update(75, "encoding output")
    payload, mime, extension = image_service.encode_bgr(stylized, request.output_format, request.quality)
    width, height = _dimensions(stylized)
    extra = {
        "operation": "cartoonize",
        "style": request.style,
        "engine": engine.info.engine,
        "engine_id": engine.info.id,
        "is_ai": engine.info.is_ai,
        "source_asset_id": source.id,
        "background": request.background,
        "notes": notes,
    }
    if not request.save_asset:
        ctx.log("save_asset=false: output kept in the job result only.")
    asset = _store_output(ctx, payload, mime, extension, "image_processed", extra)
    asset.width = width
    asset.height = height
    ctx.session.commit()

    ctx.set_result(
        asset_id=asset.id,
        content_url=f"/api/assets/{asset.id}/content",
        width=width,
        height=height,
        mime_type=mime,
        size_bytes=len(payload),
        engine=engine.info.engine,
        engine_id=engine.info.id,
        is_ai=engine.info.is_ai,
        style=request.style,
        notes=notes,
    )
    ctx.log("Cartoonization finished.")
    ctx.update(100, "completed")


def run_adjust(ctx: JobContext) -> None:
    request = AdjustRequest.model_validate(ctx.config)
    storage = get_storage()
    ctx.update(10, "loading source image")
    source = ctx.fetch_asset(request.asset_id, allowed_kinds=("image_original", "image_processed"))
    data = storage.open(source.storage_key).read()
    image = image_service.decode_bgr(data)
    ctx.update(45, "applying adjustments")
    adjusted = image_service.apply_adjustments(image, request.adjustments)
    payload, mime, extension = image_service.encode_bgr(
        adjusted, request.adjustments.output_format, request.adjustments.quality
    )
    width, height = _dimensions(adjusted)
    extra = {
        "operation": "adjust",
        "source_asset_id": source.id,
        "adjustments": request.adjustments.model_dump(mode="json"),
    }
    asset = _store_output(ctx, payload, mime, extension, "image_processed", extra)
    asset.width = width
    asset.height = height
    ctx.session.commit()
    ctx.set_result(
        asset_id=asset.id,
        content_url=f"/api/assets/{asset.id}/content",
        width=width,
        height=height,
        mime_type=mime,
        size_bytes=len(payload),
        is_ai=False,
    )
    ctx.log("Adjustments applied.")
    ctx.update(100, "completed")


def _materialise(ctx: JobContext, asset: Asset, target_dir: Path) -> Path:
    existing = get_storage().local_path(asset.storage_key)
    if existing is not None:
        return existing
    target_dir.mkdir(parents=True, exist_ok=True)
    extension = Path(asset.filename).suffix or ".bin"
    destination = target_dir / f"{asset.id}{extension}"
    with get_storage().open(asset.storage_key) as handle, destination.open("wb") as sink:
        sink.write(handle.read())
    return destination


def run_video(ctx: JobContext) -> None:
    request = VideoCreateRequest.model_validate(ctx.config)
    if not ffmpeg_available(ctx.settings):
        raise missing_ffmpeg_error()

    ctx.update(5, "preparing frames")
    temp_dir = ctx.settings.temp_dir / ctx.id
    frame_paths: list[Path] = []
    durations: list[float] = []
    effects: list[str] = []
    for index, frame in enumerate(request.frames, start=1):
        asset = ctx.fetch_asset(frame.asset_id, allowed_kinds=("image_original", "image_processed"))
        frame_paths.append(_materialise(ctx, asset, temp_dir))
        durations.append(frame.duration_seconds)
        effects.append(frame.effect)
        ctx.log(f"Frame {index}: asset {asset.id}, {frame.duration_seconds}s, effect {frame.effect}.")

    audio_plan = None
    if request.audio and request.audio.asset_id:
        audio_asset = ctx.fetch_asset(request.audio.asset_id, allowed_kinds=("audio",))
        audio_path = _materialise(ctx, audio_asset, temp_dir)
        audio_plan = AudioPlan(
            path=audio_path,
            volume=request.audio.volume,
            fade_in=request.audio.fade_in_seconds,
            fade_out=request.audio.fade_out_seconds,
            loop=request.audio.loop,
        )
        ctx.log(f"Audio track: asset {audio_asset.id}, loop={request.audio.loop}.")

    output_path = ctx.settings.render_dir / f"{ctx.id}.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plan = build_render_plan(
        frame_paths=frame_paths,
        durations=durations,
        effects=effects,
        transition_type=request.transition.type,
        transition_duration=request.transition.duration_seconds,
        aspect_ratio=request.aspect_ratio,
        resolution=request.resolution,
        fps=request.fps,
        output_path=output_path,
        audio=audio_plan,
        settings=ctx.settings,
    )
    for note in plan.notes:
        ctx.log(note)
    ctx.log(f"Rendering {plan.width}x{plan.height} @ {plan.fps}fps, {plan.total_duration:.2f}s total.")

    def progress(percent: int, stage: str) -> None:
        ctx.update(10 + int(percent * 0.85), stage)

    render_video(plan, settings=ctx.settings, on_progress=progress)
    ctx.update(96, "saving output")
    payload = output_path.read_bytes()
    asset = _store_output(ctx, payload, "video/mp4", "mp4", "video", {"operation": "video", "title": request.title})
    asset.width = plan.width
    asset.height = plan.height
    asset.duration_seconds = plan.total_duration

    video = ctx.session.get(Video, ctx.config.get("video_id", "")) if ctx.config.get("video_id") else None
    if video is None:
        video = Video(
            id=new_id(),
            project_id=ctx.project_id,
            owner=ctx.owner,
        )
    video.job_id = ctx.id
    video.output_asset_id = asset.id
    video.status = "completed"
    video.duration_seconds = plan.total_duration
    video.width = plan.width
    video.height = plan.height
    video.fps = plan.fps
    ctx.session.add(video)
    ctx.session.commit()
    ctx.session.refresh(video)

    if not ctx.settings.keep_render_temp_files:
        output_path.unlink(missing_ok=True)
        if temp_dir.exists():
            for leftover in temp_dir.glob("*"):
                leftover.unlink(missing_ok=True)
            temp_dir.rmdir()

    ctx.set_result(
        video_id=video.id,
        asset_id=asset.id,
        content_url=f"/api/assets/{asset.id}/content",
        width=plan.width,
        height=plan.height,
        fps=plan.fps,
        duration_seconds=plan.total_duration,
        size_bytes=len(payload),
        is_ai=False,
        notes=plan.notes,
    )
    ctx.log("Video render finished.")
    ctx.update(100, "completed")
