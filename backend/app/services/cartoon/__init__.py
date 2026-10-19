"""Cartoonization engines (classic filter + optional ONNX model)."""
from .base import CartoonEngine, EngineInfo, StylizeOptions
from .classic import PRESETS, ClassicFilterEngine
from .onnx import REQUIREMENTS, OnnxCartoonEngine
from .registry import (
    active_engine_id,
    build_classic,
    build_onnx,
    engine_catalog,
    onnx_available,
    resolve_engine,
    style_catalog,
)

__all__ = [
    "CartoonEngine",
    "ClassicFilterEngine",
    "EngineInfo",
    "OnnxCartoonEngine",
    "PRESETS",
    "REQUIREMENTS",
    "StylizeOptions",
    "active_engine_id",
    "build_classic",
    "build_onnx",
    "engine_catalog",
    "onnx_available",
    "resolve_engine",
    "style_catalog",
]
