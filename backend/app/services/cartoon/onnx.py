"""ONNX Runtime engine for real learned cartoonization models.

No pretrained weights are bundled: point CARTOON_ONNX_MODEL_PATH at a model you
are licensed to use, install the optional runtime (pip install onnxruntime or
onnxruntime-gpu) and the engine becomes selectable.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .base import CartoonEngine, EngineInfo, StylizeOptions

REQUIREMENTS = (
    "Provide an ONNX cartoonization model (e.g. a licensed anime/GAN generator) and set "
    "CARTOON_ONNX_MODEL_PATH to its file; install the optional runtime with "
    "'pip install onnxruntime' (CPU) or 'pip install onnxruntime-gpu' (NVIDIA CUDA). "
    "The model must accept a single float32 NCHW image tensor and return an image tensor."
)


class OnnxCartoonEngine(CartoonEngine):
    info = EngineInfo(
        id="onnx",
        label="Configured ONNX model",
        engine="onnx-model",
        is_ai=True,
        license="Depends on the model file you supply; check its licence before commercial use.",
        requires=REQUIREMENTS,
    )

    def __init__(self, model_path: str, normalize: str = "minus_one_one", provider: str = "cpu", input_size: int = 0):
        self.model_path = Path(model_path).expanduser() if model_path else None
        self.normalize = normalize
        self.provider = provider
        self.input_size = input_size
        self._session = None
        self._input_name: str | None = None
        self._last_error: str | None = None

    def _runtime(self):
        try:
            import onnxruntime  # type: ignore import-not-found
        except ImportError as exc:
            self._last_error = f"onnxruntime is not installed: {exc}"
            return None
        return onnxruntime

    def is_available(self) -> bool:
        if self.model_path is None or not self.model_path.is_file():
            self._last_error = "CARTOON_ONNX_MODEL_PATH does not point to an existing model file."
            return False
        return self._runtime() is not None

    def unavailable_reason(self) -> str:
        return self._last_error or REQUIREMENTS

    def _load(self):
        if self._session is not None:
            return self._session
        runtime = self._runtime()
        if runtime is None:
            raise RuntimeError(self._last_error or "onnxruntime unavailable")
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if self.provider == "cuda" else [
            "CPUExecutionProvider"
        ]
        session = runtime.InferenceSession(str(self.model_path), providers=providers)
        self._input_name = session.get_inputs()[0].name
        self._session = session
        return session

    def _target_size(self, session, height: int, width: int) -> tuple[int, int]:
        if self.input_size:
            return self.input_size, self.input_size
        shape = session.get_inputs()[0].shape
        try:
            model_h, model_w = int(shape[2]), int(shape[3])
            if model_h > 0 and model_w > 0:
                return model_h, model_w
        except (TypeError, ValueError, IndexError):
            pass
        return height, width

    def stylize(self, image: np.ndarray, options: StylizeOptions) -> np.ndarray:
        session = self._load()
        height, width = image.shape[:2]
        target_h, target_w = self._target_size(session, height, width)
        resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        if self.normalize == "minus_one_one":
            rgb = rgb * 2.0 - 1.0
        tensor = np.transpose(rgb, (2, 0, 1))[None, ...]
        outputs = session.run(None, {self._input_name: tensor})
        result = np.asarray(outputs[0])
        result = np.squeeze(result)
        if result.ndim == 3 and result.shape[0] in (1, 3) and result.shape[-1] not in (1, 3):
            result = np.transpose(result, (1, 2, 0))
        if result.shape[-1] == 1:
            result = np.repeat(result, 3, axis=2)
        if result.dtype != np.uint8:
            if float(result.min()) < -0.01:
                result = (np.clip(result, -1.0, 1.0) + 1.0) * 127.5
            elif float(result.max()) <= 1.01:
                result = np.clip(result, 0.0, 1.0) * 255.0
        result = np.clip(result, 0, 255).astype(np.uint8)
        result = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)
        if (target_h, target_w) != (height, width):
            result = cv2.resize(result, (width, height), interpolation=cv2.INTER_LINEAR)
        alpha = float(np.clip(options.strength, 0.05, 1.0))
        if alpha < 0.999:
            result = cv2.addWeighted(result, alpha, image, 1.0 - alpha, 0)
        return result
