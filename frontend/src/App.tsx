import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  adjust,
  cartoonize,
  createProject,
  getCapabilities,
  getHealth,
  getJob,
  getProjects,
  getStyles,
  uploadFile,
} from "./lib/api";

interface JobMeta {
  jobId: string;
  type: string;
  status: string;
  progress: number;
  result?: any;
  error_message?: string | null;
  error_code?: string | null;
  stage?: string | null;
  notes?: string[];
}

interface Asset {
  id: string;
  filename: string;
  kind: string;
  width: number | null;
  height: number | null;
  mime_type: string;
  content_url: string | null;
}

import "./App.css";

function formatError(code?: string, message?: string) {
  if (!code && !message) return "Unknown error";
  if (code === "FFMPEG_MISSING") return "FFmpeg is missing; video rendering is unavailable on this machine. Image and cartoonization features still work.";
  if (code === "MODEL_NOT_CONFIGURED") return message || "No cartoonization model is configured and the classic fallback is disabled.";
  if (code === "BACKGROUND_REMOVAL_UNAVAILABLE") return message || "Background removal is not available in this setup.";
  return message || code || "Request failed";
}

export default function App() {
  const [capabilities, setCapabilities] = useState<any | null>(null);
  const [health, setHealth] = useState<any | null>(null);
  const [styles, setStyles] = useState<any[]>([]);
  const [projects, setProjects] = useState<any[]>([]);
  const [original, setOriginal] = useState<Asset | null>(null);
  const [processed, setProcessed] = useState<Asset | null>(null);
  const [, setCompareUrl] = useState<string | null>(null);
  const [adjustUrl, setAdjustUrl] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobMeta[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [h, c, s, p] = await Promise.all([getHealth(), getCapabilities(), getStyles(), getProjects()]);
      setHealth(h);
      setCapabilities(c);
      setStyles(s);
      setProjects(p);
    } catch (err: any) {
      setError(err.message || String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const pollJob = useCallback(
    (jobId: string, timeoutMs = 60000) => {
      const started = Date.now();
      return new Promise<JobMeta>((resolve, reject) => {
        const tick = async () => {
          try {
            const job = await getJob(jobId);
            const meta: JobMeta = {
              jobId,
              type: job.type,
              status: job.status,
              progress: job.progress,
              result: job.result,
              error_message: job.error_message,
              error_code: job.error_code,
              stage: job.stage,
            };
            setJobs((prev) => [meta, ...prev.filter((m) => m.jobId !== jobId)]);
            if (job.status === "completed") {
              resolve(meta);
              return;
            }
            if (job.status === "failed") {
              reject(new Error(formatError(job.error_code, job.error_message)));
              return;
            }
            if (Date.now() - started > timeoutMs) {
              reject(new Error("Job timed out while polling for completion."));
              return;
            }
            setTimeout(tick, 400);
          } catch (err: any) {
            reject(err);
          }
        };
        tick();
      });
    },
    []
  );

  const onUpload = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const response = await uploadFile(file, "image");
      const asset: Asset = response.asset;
      setOriginal(asset);
      setProcessed(null);
      setAdjustUrl(null);
      setError(null);
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }, []);

  const onCartoonize = useCallback(
    async (style: string, engine: string) => {
      if (!original) return;
      setBusy(true);
      setError(null);
      try {
        const job = await cartoonize(original.id, { style, engine });
        const finished = await pollJob(job.id);
        const assetId = finished.result?.asset_id;
        if (assetId) {
          setProcessed({ ...original, id: assetId, kind: "image_processed", content_url: finished.result?.content_url });
          setCompareUrl(`/api/assets/${assetId}/content?variant=preview`);
        }
      } catch (err: any) {
        setError(err.message || String(err));
      } finally {
        setBusy(false);
      }
    },
    [original, pollJob]
  );

  const onAdjust = useCallback(
    async (form: HTMLFormElement) => {
      if (!processed && !original) return;
      setBusy(true);
      setError(null);
      try {
        const assetId = processed?.id || original?.id;
        const data = new FormData(form);
        const adjustments: any = {
          brightness: Number(data.get("brightness")) || 1.0,
          contrast: Number(data.get("contrast")) || 1.0,
          saturation: Number(data.get("saturation")) || 1.0,
          sharpness: Number(data.get("sharpness")) || 0.0,
          denoise: Number(data.get("denoise")) || 0.0,
          enhance: data.get("enhance") === "on",
          crop: data.get("aspect") ? { aspect_ratio: data.get("aspect") as any } : undefined,
          output_format: data.get("format") as any || "jpeg",
          quality: Number(data.get("quality")) || 92,
        };
        if (data.get("width")) adjustments.width = Number(data.get("width"));
        if (data.get("height")) adjustments.height = Number(data.get("height"));
        const job = await adjust(assetId!, adjustments);
        const finished = await pollJob(job.id);
        const assetIdOut = finished.result?.asset_id;
        if (assetIdOut) {
          setProcessed({ ...original!, id: assetIdOut, kind: "image_processed", content_url: finished.result?.content_url, width: finished.result.width, height: finished.result.height, mime_type: finished.result.mime_type || "image/jpeg" });
          setAdjustUrl(`/api/assets/${assetIdOut}/content?variant=preview`);
        }
      } catch (err: any) {
        setError(err.message || String(err));
      } finally {
        setBusy(false);
        form.reset();
      }
    },
    [original, processed, pollJob]
  );

  const engineNote = useMemo(() => {
    if (!capabilities) return "Loading…";
    if (capabilities.ffmpeg_available === false) {
      return "FFmpeg not found: image/cartoonization OK, video rendering disabled.";
    }
    return `Active engine: ${capabilities.active_engine} (AI model ${capabilities.ai_model_configured ? "configured" : "not configured"}). Classic fallback ${capabilities.classic_fallback_enabled ? "enabled" : "disabled"}.`;
  }, [capabilities]);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Cartoon AI Studio</h1>
        <div className="status-bar">
          <span>API version: {health?.version ?? "—"}</span>
          <span>Storage: {health?.storage_provider ?? "local"}</span>
          <span>{engineNote}</span>
        </div>
      </header>

      <main className="app__main">
        <section className="panel">
          <h2>Upload</h2>
          <button className="button" disabled={busy} onClick={() => fileRef.current?.click()}>
            {busy ? "Working…" : "Choose image"}
          </button>
          <input ref={fileRef} type="file" accept="image/jpeg,image/jpg,image/png,image/webp" hidden onChange={onUpload} />
          {original && (
            <div className="asset-card">
              <p className="asset-card__name">{original.filename}</p>
              <p className="asset-card__meta">{original.width}×{original.height} · {original.mime_type}</p>
              <img src={`/api/assets/${original.id}/content?variant=preview`} alt="Original preview" />
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Cartoonize</h2>
          <div className="grid">
            {styles.map((style) => (
              <div key={style.id} className="style-card">
                <h3>{style.label}</h3>
                <p>{style.description}</p>
                <div className="style-card__footer">
                  <span>engine: {style.engine} · {style.is_ai ? "AI" : "non-AI"}</span>
                  <button className="button button--small" disabled={!original || busy} onClick={() => onCartoonize(style.id, capabilities?.active_engine === "onnx" ? "onnx" : "auto")}>
                    Run {style.id}
                  </button>
                </div>
              </div>
            ))}
          </div>
          {processed && (
            <div className="asset-card">
              <p className="asset-card__name">Cartoon output</p>
              <p className="asset-card__meta">engine: {jobs[0]?.result?.engine} · {jobs[0]?.result?.is_ai ? "AI" : "non-AI"}</p>
              <img src={`/api/assets/${processed.id}/content?variant=preview`} alt="Cartoon preview" />
              {jobs[0]?.result?.notes?.length > 0 && (
                <ul className="notes">
                  {jobs[0].result.notes.map((n: string) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>

        <section className="panel">
          <h2>Adjust</h2>
          <form className="form" onSubmit={(e) => { e.preventDefault(); onAdjust(e.currentTarget); }}>
            <div className="form__grid">
              <label>Brightness <input type="range" min="0.5" max="2.0" step="0.05" name="brightness" defaultValue="1.0" /></label>
              <label>Contrast <input type="range" min="0.5" max="2.0" step="0.05" name="contrast" defaultValue="1.0" /></label>
              <label>Saturation <input type="range" min="0.0" max="2.0" step="0.05" name="saturation" defaultValue="1.0" /></label>
              <label>Sharpness <input type="range" min="0.0" max="4.0" step="0.1" name="sharpness" defaultValue="0.0" /></label>
              <label>Denoise <input type="range" min="0.0" max="1.0" step="0.05" name="denoise" defaultValue="0.0" /></label>
              <label>Enhance <input type="checkbox" name="enhance" /></label>
              <label>Crop <select name="aspect"><option value="">none</option><option value="1:1">1:1</option><option value="16:9">16:9</option><option value="4:3">4:3</option><option value="3:4">3:4</option><option value="9:16">9:16</option></select></label>
              <label>Width <input type="number" name="width" min="32" max="4096" placeholder="auto" /></label>
              <label>Height <input type="number" name="height" min="32" max="4096" placeholder="auto" /></label>
              <label>Format <select name="format"><option value="jpeg">JPEG</option><option value="png">PNG</option><option value="webp">WebP</option></select></label>
              <label>Quality <input type="range" min="50" max="100" step="2" name="quality" defaultValue="92" /></label>
            </div>
            <button className="button" disabled={busy || (!original && !processed)}>Apply adjustments</button>
          </form>
          {adjustUrl && <img className="result-img" src={adjustUrl} alt="Adjusted preview" />}
        </section>

        <section className="panel">
          <h2>Recent Jobs</h2>
          <div className="job-list">
            {jobs.slice(0, 8).map((job) => (
              <article key={job.jobId} className="job">
                <header>
                  <strong>{job.type}</strong> · {job.status} · {job.progress}%
                </header>
                {job.result?.engine && <p>engine: {job.result.engine} · is_ai: {String(job.result.is_ai)}</p>}
                {job.error_message && <p className="danger">{job.error_message}</p>}
              </article>
            ))}
            {jobs.length === 0 && <p className="muted">No jobs yet.</p>}
          </div>
        </section>

        <section className="panel">
          <h2>Projects</h2>
          <div className="inline">
            <button className="button button--small" disabled={busy} onClick={async () => { const name = prompt("Project name"); if(name){ await createProject(name); await refresh(); } }}>
              New project
            </button>
          </div>
          <ul className="list">
            {projects.map((p) => (
              <li key={p.id}>{p.name} · {p.status} · {p.id.slice(0,6)}</li>
            ))}
          </ul>
        </section>
      </main>

      {error && <div className="toast">{error}</div>}
      {busy && <div className="spinner" aria-live="polite" />}
    </div>
  );
}
