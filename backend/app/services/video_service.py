"""Video pipeline: builds the FFmpeg plan for an image sequence + audio.

The filter builders are pure functions so they can be unit-tested without
FFmpeg installed; only `render_video` needs the FFmpeg binary.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..core.config import Settings, get_settings
from ..core.errors import AppError
from .ffmpeg_tools import run_ffmpeg

ASPECT_SIZES: dict[str, dict[str, tuple[int, int]]] = {
    "480p": {"16:9": (854, 480), "9:16": (480, 854), "1:1": (480, 480), "4:3": (640, 480), "3:4": (480, 640)},
    "720p": {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (720, 720), "4:3": (960, 720), "3:4": (720, 960)},
    "1080p": {
        "16:9": (1920, 1080),
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "4:3": (1440, 1080),
        "3:4": (1080, 1440),
    },
}

UPSCALE_FACTOR = 1.5


def resolve_size(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    try:
        return ASPECT_SIZES[resolution][aspect_ratio]
    except KeyError as exc:
        raise AppError(
            "UNSUPPORTED_VIDEO_SIZE",
            f"Resolution '{resolution}' with aspect ratio '{aspect_ratio}' is not supported.",
            details={"resolutions": sorted(ASPECT_SIZES), "aspect_ratios": sorted(ASPECT_SIZES["720p"])},
        ) from exc


def effective_transition_duration(transition_type: str, requested: float, durations: Sequence[float], frame_count: int) -> float:
    if transition_type == "none" or frame_count < 2:
        return 0.0
    shortest = min(durations)
    if shortest <= 0.6:
        return 0.0
    return round(min(requested, (shortest / 2) - 0.05), 3)


def effect_expressions(effect: str, frames: int) -> tuple[str, str, str]:
    n = max(1, frames)
    progress = f"(on/{n})"
    if effect == "zoom_in":
        return f"min(1.0+0.15*{progress},1.15)", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if effect == "zoom_out":
        return f"max(1.15-0.15*{progress},1.0)", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if effect == "pan_left":
        return "1.12", f"(iw-iw/zoom)*(1-{progress})", "(ih-ih/zoom)/2"
    if effect == "pan_right":
        return "1.12", f"(iw-iw/zoom)*{progress}", "(ih-ih/zoom)/2"
    if effect == "pan_up":
        return "1.12", "(iw-iw/zoom)/2", f"(ih-ih/zoom)*(1-{progress})"
    if effect == "pan_down":
        return "1.12", "(iw-iw/zoom)/2", f"(ih-ih/zoom)*{progress}"
    return "1.0", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"


def build_segment_filter(index: int, size: tuple[int, int], fps: int, duration: float, effect: str) -> str:
    width, height = size
    scaled_w = int(math.ceil(width * UPSCALE_FACTOR / 2) * 2)
    scaled_h = int(math.ceil(height * UPSCALE_FACTOR / 2) * 2)
    frames = max(1, round(duration * fps))
    zoom, x_expr, y_expr = effect_expressions(effect, frames)
    zoompan = (
        f"zoompan=z='{zoom}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps}"
    )
    return (
        f"[{index}:v]scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
        f"crop={scaled_w}:{scaled_h},{zoompan},trim=duration={duration:.3f},"
        f"setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
    )


def build_video_filter(
    durations: Sequence[float],
    effects: Sequence[str],
    transition_type: str,
    transition_duration: float,
    size: tuple[int, int],
    fps: int,
) -> tuple[str, str, float]:
    """Return (filter_graph, output_label, total_duration_seconds)."""
    if len(durations) != len(effects):
        raise AppError("INVALID_VIDEO_PLAN", "Each frame needs a duration and an effect.")
    segment_filters = [
        build_segment_filter(index, size, fps, duration, effect)
        for index, (duration, effect) in enumerate(zip(durations, effects, strict=True))
    ]
    transition = effective_transition_duration(transition_type, transition_duration, durations, len(durations))

    if len(durations) == 1 or transition <= 0:
        if len(durations) == 1:
            graph = ",".join(segment_filters)
            graph += f";[v0]null[vout]"
            return graph, "vout", float(durations[0])
        concat_inputs = "".join(f"[v{i}]" for i in range(len(durations)))
        graph = ",".join(segment_filters) + f";{concat_inputs}concat=n={len(durations)}:v=1:a=0[vout]"
        return graph, "vout", float(sum(durations))

    graph_parts = list(segment_filters)
    accumulated = float(durations[0])
    previous = "v0"
    for index in range(1, len(durations)):
        offset = max(0.0, accumulated - transition)
        label = f"x{index}" if index < len(durations) - 1 else "vout"
        graph_parts.append(
            f"[{previous}][v{index}]xfade=transition={transition_type}:duration={transition:.3f}:"
            f"offset={offset:.3f}[{label}]"
        )
        accumulated = accumulated + float(durations[index]) - transition
        previous = label
    return ";".join(graph_parts), previous, max(0.1, accumulated)


@dataclass
class AudioPlan:
    path: Path
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    loop: bool = True
    filter: str = ""
    label: str = "aout"


@dataclass
class RenderPlan:
    args: list[str]
    filter_complex: str
    total_duration: float
    width: int
    height: int
    fps: int
    notes: list[str] = field(default_factory=list)


def build_audio_filter(audio: AudioPlan, input_index: int, total_duration: float) -> str:
    fade_in = max(0.0, audio.fade_in)
    fade_out = max(0.0, audio.fade_out)
    chain = [f"[{input_index}:a]volume={audio.volume:.3f}"]
    if fade_in > 0:
        chain.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        start = max(0.0, total_duration - fade_out)
        chain.append(f"afade=t=out:st={start:.3f}:d={fade_out:.3f}")
    if not audio.loop:
        chain.append("apad")
    chain.append(f"atrim=0:{total_duration:.3f}")
    chain.append("asetpts=PTS-STARTPTS")
    return ",".join(chain).replace(f"[{input_index}:a]volume", f"[{input_index}:a]volume") + f"[{audio.label}]"


def build_render_plan(
    frame_paths: Sequence[Path],
    durations: Sequence[float],
    effects: Sequence[str],
    transition_type: str,
    transition_duration: float,
    aspect_ratio: str,
    resolution: str,
    fps: int,
    output_path: Path,
    audio: AudioPlan | None = None,
    settings: Settings | None = None,
) -> RenderPlan:
    settings = settings or get_settings()
    if not frame_paths:
        raise AppError("INVALID_VIDEO_PLAN", "At least one frame image is required.")
    missing = [str(path) for path in frame_paths if not Path(path).is_file()]
    if missing:
        raise AppError("FRAME_FILE_MISSING", "One or more frame images are missing on disk.", details={"missing": missing})

    size = resolve_size(resolution, aspect_ratio)
    filter_graph, out_label, total_duration = build_video_filter(
        durations, effects, transition_type, transition_duration, size, fps
    )
    notes: list[str] = []
    if transition_type != "none" and effective_transition_duration(transition_type, transition_duration, durations, len(durations)) == 0:
        notes.append("Transition disabled: it was longer than half of the shortest frame duration.")

    input_args: list[str] = []
    for path, duration in zip(frame_paths, durations, strict=True):
        input_args += ["-loop", "1", "-framerate", str(fps), "-t", f"{duration:.3f}", "-i", str(path)]

    audio_label = None
    if audio is not None:
        if audio.loop:
            input_args += ["-stream_loop", "-1"]
        input_args += ["-i", str(audio.path)]
        audio_index = len(frame_paths)
        filter_graph = f"{filter_graph};{build_audio_filter(audio, audio_index, total_duration)}"
        audio_label = audio.label
    elif transition_type != "none" and len(durations) > 1:
        notes.append("Video has no audio track.")

    args = [
        "-y",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        *input_args,
        "-filter_complex",
        filter_graph,
        "-map",
        f"[{out_label}]",
    ]
    if audio_label:
        args += ["-map", f"[{audio_label}]"]
    args += [
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "21",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]
    if audio_label:
        args += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    args += [str(output_path)]
    if not settings.keep_render_temp_files and notes:
        notes.append("Intermediate files are removed after a successful render.")
    return RenderPlan(
        args=args,
        filter_complex=filter_graph,
        total_duration=total_duration,
        width=size[0],
        height=size[1],
        fps=fps,
        notes=notes,
    )


def render_video(
    plan: RenderPlan,
    settings: Settings | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> None:
    run_ffmpeg(plan.args, settings=settings, on_progress=on_progress, total_duration=plan.total_duration)
