"""Engine registry: resolves which cartoonization engine actually runs."""
from __future__ import annotations

from ...core.config import Settings, get_settings
from ...core.errors import AppError, unsupported
from .base import CartoonEngine, EngineInfo, StylizeOptions
from .classic import PRESETS, ClassicFilterEngine
from .onnx import REQUIREMENTS, OnnxCartoonEngine

STYLE_DESCRIPTIONS: dict[str, str] = {
    "anime": "Smooth colour areas with clean outlines (classic filter preset).",
    "comic": "Bolder ink lines and punchier colours (classic filter preset).",
    "ink": "Heavy black line work with few colour levels (classic filter preset).",
    "illustration": "Soft shading with more colour levels (classic filter preset).",
    "sketch": "Pencil-style line drawing (classic filter preset).",
    "3d": "Glossy, slightly bloomed look (classic filter preset).",
    "pastel": "Light, low-contrast pastel tones (classic filter preset).",
}

STYLE_LABELS: dict[str, str] = {
    "anime": "Anime",
    "comic": "Comic",
    "ink": "Ink",
    "illustration": "Illustration",
    "sketch": "Sketch",
    "3d": "3D-ish",
    "pastel": "Pastel",
}


def build_classic() -> ClassicFilterEngine:
    return ClassicFilterEngine()


def build_onnx(settings: Settings | None = None) -> OnnxCartoonEngine:
    settings = settings or get_settings()
    return OnnxCartoonEngine(
        model_path=settings.cartoon_onnx_model_path,
        normalize=settings.cartoon_onnx_normalize,
        provider=settings.cartoon_onnx_provider,
        input_size=settings.cartoon_onnx_input_size,
    )


def onnx_available(settings: Settings | None = None) -> bool:
    return build_onnx(settings).is_available()


def resolve_engine(
    requested: str,
    allow_classic_fallback: bool,
    settings: Settings | None = None,
) -> tuple[CartoonEngine, dict[str, object]]:
    """Return the engine that will run plus metadata explaining the choice."""
    settings = settings or get_settings()
    fallback_allowed = allow_classic_fallback and settings.allow_classic_fallback
    requested = (requested or "auto").lower()

    if requested == "classic":
        return build_classic(), {"resolved_engine": "classic", "note": "Classic OpenCV filter requested explicitly."}

    if requested == "onnx":
        engine = build_onnx(settings)
        if engine.is_available():
            return engine, {"resolved_engine": "onnx"}
        if fallback_allowed:
            return build_classic(), {
                "resolved_engine": "classic",
                "fallback_used": True,
                "note": "A learned model is not configured, so the classic OpenCV filter was used instead.",
                "requested_engine_unavailable_reason": engine.unavailable_reason(),
            }
        raise unsupported(
            "MODEL_NOT_CONFIGURED",
            "No cartoonization model is configured and the classic fallback is disabled.",
            {"requirements": REQUIREMENTS, "fallback_available": True},
        )

    engine = build_onnx(settings)
    if engine.is_available():
        return engine, {"resolved_engine": "onnx"}
    if fallback_allowed:
        return build_classic(), {
            "resolved_engine": "classic",
            "fallback_used": True,
            "note": "No learned model is configured; the classic OpenCV filter was used. Output is not AI-generated.",
        }
    raise unsupported(
        "MODEL_NOT_CONFIGURED",
        "No cartoonization model is configured and the classic fallback is disabled.",
        {"requirements": REQUIREMENTS, "fallback_available": True},
    )


def active_engine_id(settings: Settings | None = None) -> str:
    return "onnx" if onnx_available(settings) else "classic"


def engine_catalog(settings: Settings | None = None) -> list[EngineInfo]:
    settings = settings or get_settings()
    return [build_onnx(settings).info, build_classic().info]


def style_catalog(settings: Settings | None = None) -> list[dict[str, object]]:
    settings = settings or get_settings()
    onnx_ready = onnx_available(settings)
    fallback_allowed = settings.allow_classic_fallback
    if onnx_ready:
        engine_id, is_ai = "onnx-model", True
    else:
        engine_id, is_ai = "classic-filter", False
    styles: list[dict[str, object]] = []
    for style_id in PRESETS:
        description = STYLE_DESCRIPTIONS.get(style_id, "")
        if not onnx_ready and fallback_allowed:
            description = f"{description} No learned model configured, so this preset runs the classic filter."
        styles.append(
            {
                "id": style_id,
                "label": STYLE_LABELS.get(style_id, style_id.title()),
                "description": description,
                "engine": engine_id,
                "is_ai": is_ai,
            }
        )
    return styles


__all__ = [
    "ClassicFilterEngine",
    "OnnxCartoonEngine",
    "REQUIREMENTS",
    "StylizeOptions",
    "STYLE_LABELS",
    "active_engine_id",
    "build_classic",
    "build_onnx",
    "engine_catalog",
    "onnx_available",
    "resolve_engine",
    "style_catalog",
]
