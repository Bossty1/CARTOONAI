# Cartoon AI Studio

Cartoon AI Studio is a small, self-contained web app that turns images into cartoon-style artwork and builds simple image→video sequences. It is built for **honest results**: when the "classic OpenCV filter" is used, it is **never** labelled as artificial intelligence.

## Quick start

### Backend (local Python, no Docker)
1. `cd cartoon-ai-studio/backend`
2. `py -m venv .venv && .\.venv\Scripts\Activate.ps1` (Windows) or `python -m venv .venv && source .venv/bin/activate` (Linux/macOS)
3. `pip install -r requirements.txt`
4. `uvicorn app.main:app --reload` (defaults to http://127.0.0.1:8000)

### Frontend (Vite/React/TS)
1. `cd cartoon-ai-studio/frontend`
2. `npm install`
3. `npm run dev` (defaults to http://127.0.0.1:5190, proxies `/api` to `http://127.0.0.1:8000`)

### Docker Compose
1. `cd cartoon-ai-studio`
2. `docker compose up --build` (FFmpeg is bundled in the image)
3. Open http://localhost:8000/docs and http://localhost:5173 (adjust to your Vite port if needed)

## Features
- Upload JPEG/PNG/WebP images and WAV/MP3 audio (with graceful fallbacks for unsupported formats)
- Cartoonization with a **classic OpenCV filter** (honestly reported as `engine="classic-filter"` and `is_ai=false`). A configurable ONNX runtime is supported; no bundled weights.
- Image adjustments: brightness/contrast/saturation/sharpness/denoise/enhance, crop (aspect + free region), resize, output format/quality
- Video builder: image sequence, per-frame duration/effects (zoom/pan), transitions, aspect ratio/resolution/FPS, optional audio (with fades/loop)
- Job tracking with progress, stage and logs; error envelope for all failures
- Local storage by default (SQLite database, filesystem); S3/GCS adapters exist but need optional SDKs and credentials
- Honest labels: background removal is not faked (rejected), background "blur" is a vignette; FFmpeg missing produces `FFMPEG_MISSING` (503) without breaking image/cartoonization features

## Environment variables
See `.env.example` for the complete list. Common ones:
- `STORAGE_PROVIDER` – `local`, `s3` or `gcs`
- `PUBLIC_BASE_URL` – used to suggest share URLs (only works if publicly reachable)
- `CARTOON_ONNX_MODEL_PATH` – path to a licensed ONNX model (triggers AI label when available)
- `FFMPEG_BINARY`, `FFPROBE_BINARY` – custom paths if not on `PATH`
- `ALLOW_CLASSIC_FALLBACK` – `true` (recommended) to keep the app working without a learned model

## Tests
```bash
cd cartoon-ai-studio/backend
py -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest
```
All 65 tests pass. The suite uses the classic filter in-process and does not require FFmpeg for the non-video tests (video tests detect availability).

## Notes on honesty and licensing
- **No mislabelling.** Every cartoonization result reports `engine`, `engine_id`, `is_ai` and human-readable notes. When falling back to the classic filter, the API and UI state it explicitly.
- **No bundled AI weights.** Install and configure ONNX models at your own discretion and verify their licence.
- **Local-first.** No telemetry; forms are client-side and no secrets are returned to the frontend.
- **Windows-friendly.** The instructions use PowerShell (`py`, `.\.venv\Scripts\Activate.ps1`). Unix shells need `python -m venv` + `source .venv/bin/activate`.

## Integration with the existing CARTOON_SOL site
This is an **add-on** placed in `cartoon-ai-studio/` inside the repo root. The original Vite site (root level) is not modified or rebuilt by this app. The Studio has its own dependencies, port (frontend 5190 by default) and configuration. If you prefer to deploy it separately, copy this subfolder to its own service.
