"""Image decoding, validation, adjustments and encoding."""
from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps, UnidentifiedImageError

from ..core.config import Settings, get_settings
from ..core.errors import AppError, payload_too_large, unsupported

ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
PIL_FORMAT_TO_MIME: dict[str, str] = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
FORMAT_EXTENSION: dict[str, str] = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "webp": "webp"}

Image.MAX_IMAGE_PIXELS = 400_000_000


@dataclass(frozen=True)
class ImageInfo:
    mime_type: str
    extension: str
    width: int
    height: int
    mode: str
    pil_format: str


def sniff_image_info(data: bytes, settings: Settings | None = None) -> ImageInfo:
    settings = settings or get_settings()
    if not data:
        raise AppError("EMPTY_UPLOAD", "The uploaded file is empty.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            pil_format = (image.format or "").upper()
            width, height = image.size
            mode = image.mode
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError(
            "UNSUPPORTED_IMAGE",
            "The file is not a readable JPEG, PNG or WebP image.",
            details={"reason": str(exc), "allowed": sorted(set(ALLOWED_IMAGE_TYPES))},
        ) from exc

    mime = PIL_FORMAT_TO_MIME.get(pil_format)
    if mime is None:
        raise AppError(
            "UNSUPPORTED_IMAGE_TYPE",
            f"Format {pil_format or 'unknown'} is not supported.",
            details={"allowed": sorted(set(ALLOWED_IMAGE_TYPES))},
        )
    if width * height > settings.max_image_pixels:
        raise payload_too_large(
            "IMAGE_TOO_LARGE",
            f"Image has {width * height:,} pixels; the limit is {settings.max_image_pixels:,}.",
            {"width": width, "height": height, "max_pixels": settings.max_image_pixels},
        )
    side = min(width, height)
    if side < settings.min_image_side:
        raise AppError(
            "IMAGE_TOO_SMALL",
            f"Images must be at least {settings.min_image_side}px on the shortest side.",
            details={"width": width, "height": height},
        )
    if max(width, height) > settings.max_image_side:
        raise payload_too_large(
            "IMAGE_DIMENSION_TOO_LARGE",
            f"The longest side must be at most {settings.max_image_side}px.",
            {"width": width, "height": height, "max_side": settings.max_image_side},
        )
    return ImageInfo(
        mime_type=mime,
        extension=ALLOWED_IMAGE_TYPES[mime],
        width=width,
        height=height,
        mode=mode,
        pil_format=pil_format,
    )


def decode_bgr(data: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            rgb = image.convert("RGB")
            array = np.asarray(rgb, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise AppError("UNSUPPORTED_IMAGE", "The image could not be decoded.", details={"reason": str(exc)}) from exc
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def encode_bgr(image: np.ndarray, output_format: str = "jpeg", quality: int = 92) -> tuple[bytes, str, str]:
    fmt = output_format.lower()
    if fmt not in FORMAT_EXTENSION:
        raise AppError("UNSUPPORTED_OUTPUT_FORMAT", f"Output format '{output_format}' is not supported.")
    pil_format = "PNG" if fmt == "png" else ("WEBP" if fmt == "webp" else "JPEG")
    mime = PIL_FORMAT_TO_MIME[pil_format]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    buffer = io.BytesIO()
    if pil_format == "JPEG":
        Image.fromarray(rgb).save(buffer, format=pil_format, quality=int(quality), optimize=True, progressive=True)
    elif pil_format == "WEBP":
        Image.fromarray(rgb).save(buffer, format=pil_format, quality=int(quality), method=5)
    else:
        Image.fromarray(rgb).save(buffer, format=pil_format, optimize=True)
    return buffer.getvalue(), mime, FORMAT_EXTENSION[fmt]


def make_preview(data: bytes, max_side: int = 1400, quality: int = 82) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def apply_adjustments(image: np.ndarray, adjustments, settings: Settings | None = None) -> np.ndarray:
    """Apply brightness/contrast/saturation/sharpness/denoise/crop/resize."""
    settings = settings or get_settings()
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)

    if adjustments.denoise and adjustments.denoise > 0:
        strength = 3 + int(adjustments.denoise * 12)
        bgr = cv2.fastNlMeansDenoisingColored(image, None, strength, strength, 7, 21)
        pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    if adjustments.enhance:
        pil = ImageOps.autocontrast(pil, cutoff=1)

    if abs(adjustments.brightness - 1.0) > 1e-3:
        pil = ImageEnhance.Brightness(pil).enhance(float(adjustments.brightness))
    if abs(adjustments.contrast - 1.0) > 1e-3:
        pil = ImageEnhance.Contrast(pil).enhance(float(adjustments.contrast))
    if abs(adjustments.saturation - 1.0) > 1e-3:
        pil = ImageEnhance.Color(pil).enhance(float(adjustments.saturation))
    if adjustments.sharpness > 0:
        pil = ImageEnhance.Sharpness(pil).enhance(1.0 + float(adjustments.sharpness))

    if adjustments.crop is not None:
        pil = _crop(pil, adjustments.crop)
    if adjustments.width or adjustments.height:
        pil = _resize(pil, adjustments.width, adjustments.height, settings)

    return cv2.cvtColor(np.asarray(pil.convert("RGB"), dtype=np.uint8), cv2.COLOR_RGB2BGR)


def _crop(pil: Image.Image, crop) -> Image.Image:
    width, height = pil.size
    if crop.x is not None and crop.y is not None and crop.width and crop.height:
        left = int(crop.x * width)
        top = int(crop.y * height)
        right = min(width, left + int(crop.width * width))
        bottom = min(height, top + int(crop.height * height))
        if right - left < 16 or bottom - top < 16:
            raise AppError("INVALID_CROP", "The crop region is too small.")
        return pil.crop((left, top, right, bottom))
    if crop.aspect_ratio:
        ratio_w, ratio_h = (float(part) for part in crop.aspect_ratio.split(":"))
        target = ratio_w / ratio_h
        current = width / height
        if current > target:
            new_width = int(height * target)
            left = (width - new_width) // 2
            return pil.crop((left, 0, left + new_width, height))
        new_height = int(width / target)
        top = (height - new_height) // 2
        return pil.crop((0, top, width, top + new_height))
    return pil


def _resize(pil: Image.Image, width: int | None, height: int | None, settings: Settings) -> Image.Image:
    source_w, source_h = pil.size
    if width and height:
        target = (width, height)
    elif width:
        target = (width, max(1, round(source_h * width / source_w)))
    else:
        target = (max(1, round(source_w * height / source_h)), height)
    if min(target) < settings.min_image_side:
        raise AppError("IMAGE_TOO_SMALL", f"Resized images must be at least {settings.min_image_side}px on both sides.")
    if max(target) > settings.max_image_side:
        raise payload_too_large("IMAGE_DIMENSION_TOO_LARGE", f"Resized images must stay under {settings.max_image_side}px.")
    return pil.resize(target, Image.Resampling.LANCZOS)


def apply_background(image: np.ndarray, mode: str) -> tuple[np.ndarray, str]:
    """Soft vignette blur. Segmentation-based removal is intentionally not faked."""
    if mode == "keep":
        return image, "Background kept unchanged."
    if mode == "remove":
        raise unsupported(
            "BACKGROUND_REMOVAL_UNAVAILABLE",
            "Background removal requires a segmentation model, which is not configured.",
            {"available_options": ["keep", "blur"], "docs": "See cartoon-ai-studio/models/README.md"},
        )
    height, width = image.shape[:2]
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=max(4.0, min(width, height) / 90))
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(mask, (width // 2, height // 2), (int(width * 0.36), int(height * 0.44)), 0, 0, 360, 255, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=max(8.0, min(width, height) / 25))
    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    return (image.astype(np.float32) * alpha + blurred.astype(np.float32) * (1 - alpha)).astype(np.uint8), (
        "Vignette blur applied (classic effect, not segmentation-based background removal)."
    )
