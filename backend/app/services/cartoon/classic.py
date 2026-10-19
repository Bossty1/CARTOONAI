"""Classical OpenCV cartoon filter.

This is an image-processing filter set built with bilateral smoothing, edge
detection and colour posterisation. It is intentionally NOT advertised as
artificial intelligence: results are reported with engine="classic-filter"
and is_ai=false so the client can label them honestly.
"""
from __future__ import annotations

import cv2
import numpy as np

from .base import CartoonEngine, EngineInfo, StylizeOptions

PRESETS: dict[str, dict[str, object]] = {
    "anime": {"mode": "toon", "sigma": 110, "lines": 0.55, "sat": 1.25, "levels_offset": 2},
    "comic": {"mode": "toon", "sigma": 90, "lines": 1.0, "sat": 1.5, "levels_offset": -2},
    "ink": {"mode": "toon", "sigma": 80, "lines": 1.6, "sat": 0.9, "levels_offset": -4},
    "illustration": {"mode": "toon", "sigma": 130, "lines": 0.35, "sat": 1.15, "levels_offset": 4},
    "sketch": {"mode": "sketch", "sigma": 100, "lines": 1.0, "sat": 0.4, "levels_offset": 0},
    "3d": {"mode": "stylize", "sigma": 140, "lines": 0.2, "sat": 1.25, "levels_offset": 0},
    "pastel": {"mode": "pastel", "sigma": 150, "lines": 0.15, "sat": 0.85, "levels_offset": 6},
}

DEFAULT_PRESET = PRESETS["anime"]


class ClassicFilterEngine(CartoonEngine):
    info = EngineInfo(
        id="classic",
        label="Classic OpenCV filter",
        engine="classic-filter",
        is_ai=False,
        license="Same licence as OpenCV (Apache-2.0) - no third-party model weights.",
        requires="opencv-python-headless and numpy (already installed with the backend).",
    )

    def is_available(self) -> bool:
        return True

    def stylize(self, image: np.ndarray, options: StylizeOptions) -> np.ndarray:
        preset = PRESETS.get(options.style, DEFAULT_PRESET)
        mode = str(preset["mode"])
        sigma = float(preset["sigma"])
        saturation = float(preset["sat"])
        line_strength = float(preset["lines"]) * max(options.edge_strength * 2.0, 0.2)
        levels = int(np.clip(options.color_levels + int(preset["levels_offset"]), 2, 32))
        iterations = max(1, options.smooth_iterations)

        if mode == "sketch":
            return self._sketch(image, options, saturation)
        if mode in {"stylize", "pastel"} and hasattr(cv2, "stylization"):
            base = self._stylize_soft(image, mode, sigma, iterations)
        else:
            base = self._toon_base(image, sigma, iterations)

        base = self._posterize(base, levels)
        base = self._adjust_saturation(base, saturation)
        if mode == "toon" or line_strength > 0.05:
            edges = self._edges(image, line_strength)
            base = cv2.bitwise_and(base, edges) if line_strength > 0 else base
        if mode == "3d":
            base = self._bloom(base)
        return self._blend(image, base, options.strength)

    def _toon_base(self, image: np.ndarray, sigma: float, iterations: int) -> np.ndarray:
        result = image
        for _ in range(iterations):
            result = cv2.bilateralFilter(result, 9, sigma, sigma)
        return cv2.medianBlur(result, 5)

    def _stylize_soft(self, image: np.ndarray, mode: str, sigma: float, iterations: int) -> np.ndarray:
        base = self._toon_base(image, sigma, iterations)
        flags = cv2.edgePreservingFilter(base, flags=2, sigma_s=int(60 + sigma / 2), sigma_r=0.4) if hasattr(
            cv2, "edgePreservingFilter"
        ) else base
        if mode == "pastel":
            flags = cv2.convertScaleAbs(flags, alpha=1.05, beta=18)
        return flags

    def _sketch(self, image: np.ndarray, options: StylizeOptions, saturation: float) -> np.ndarray:
        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        inverted = cv2.bitwise_not(grey)
        blurred = cv2.GaussianBlur(inverted, (0, 0), sigmaX=float(np.clip(options.smooth_iterations * 6, 4, 24)))
        sketch = cv2.divide(grey, 255 - blurred, scale=256)
        canvas = cv2.cvtColor(sketch, cv2.COLOR_GRAY2BGR)
        canvas = self._adjust_saturation(canvas, saturation)
        return self._blend(image, canvas, options.strength)

    def _posterize(self, image: np.ndarray, levels: int) -> np.ndarray:
        step = max(1, 256 // levels)
        quantized = (image.astype(np.int32) // step) * step + step // 2
        return np.clip(quantized, 0, 255).astype(np.uint8)

    def _edges(self, image: np.ndarray, line_strength: float) -> np.ndarray:
        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        grey = cv2.medianBlur(grey, 5)
        block = 9
        edges = cv2.adaptiveThreshold(
            grey, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, block, max(1, int(9 - line_strength * 6))
        )
        if line_strength > 1.0:
            kernel = np.ones((2, 2), np.uint8)
            edges = cv2.erode(edges, kernel, iterations=int(line_strength))
        return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

    def _adjust_saturation(self, image: np.ndarray, factor: float) -> np.ndarray:
        if abs(factor - 1.0) < 1e-3:
            return image
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * factor, 0, 255)
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    def _bloom(self, image: np.ndarray) -> np.ndarray:
        blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=6)
        return cv2.addWeighted(image, 0.82, blurred, 0.18, 0)

    def _blend(self, original: np.ndarray, stylized: np.ndarray, strength: float) -> np.ndarray:
        alpha = float(np.clip(strength, 0.05, 1.0))
        return cv2.addWeighted(stylized, alpha, original, 1.0 - alpha, 0)
