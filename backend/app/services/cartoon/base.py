"""Cartoonization engine interface.

Every engine advertises whether it is a real machine-learning model or a
classical image-processing filter, so the API and UI never mislabel output.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class EngineInfo:
    id: str
    label: str
    engine: str
    is_ai: bool
    license: str
    requires: str


@dataclass(frozen=True)
class StylizeOptions:
    style: str = "anime"
    strength: float = 0.85
    edge_strength: float = 0.6
    color_levels: int = 8
    smooth_iterations: int = 2


class CartoonEngine(abc.ABC):
    """Base class for cartoonization engines operating on BGR uint8 arrays."""

    info: EngineInfo

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Whether the engine can run right now with the current configuration."""

    @abc.abstractmethod
    def stylize(self, image: np.ndarray, options: StylizeOptions) -> np.ndarray:
        """Return a stylized BGR uint8 image."""

    def unavailable_reason(self) -> str:
        return "The engine is not available with the current configuration."
