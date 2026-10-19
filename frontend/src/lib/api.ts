const apiBase = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { code: "HTTP_ERROR", message: response.statusText } }));
    const e: any = new Error(error?.error?.message || response.statusText);
    e.code = error?.error?.code;
    e.details = error?.error?.details;
    throw e;
  }
  if (response.status === 204) {
    return {} as T;
  }
  return response.json() as Promise<T>;
}

export function getHealth() {
  return request<{ status: string; version: string; ffmpeg_available: boolean; storage_provider: string }>("/health");
}

export function getCapabilities() {
  return request<any>("/capabilities");
}

export function getStyles() {
  return request<any[]>("/styles");
}

export function getProjects() {
  return request<any[]>("/projects");
}

export function createProject(name: string) {
  return request<any>("/projects", { method: "POST", body: JSON.stringify({ name }) });
}

export function uploadFile(file: File, kind: "image" | "audio" = "image", projectId?: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  if (projectId) form.append("project_id", projectId);
  return fetch(`${apiBase}/uploads`, { method: "POST", body: form }).then(async (r) => {
    if (!r.ok) {
      const error = await r.json().catch(() => ({ error: { code: "HTTP_ERROR", message: r.statusText } }));
      throw Object.assign(new Error(error?.error?.message), { code: error?.error?.code });
    }
    return r.json() as Promise<any>;
  });
}

export function cartoonize(assetId: string, payload?: Partial<any>) {
  const body = { asset_id: assetId, ...(payload || {}) };
  return request<any>("/cartoonize", { method: "POST", body: JSON.stringify(body) });
}

export function adjust(assetId: string, adjustments: any) {
  const body = { asset_id: assetId, adjustments };
  return request<any>("/images/adjust", { method: "POST", body: JSON.stringify(body) });
}

export function getJob(jobId: string) {
  return request<any>(`/jobs/${jobId}`);
}

export function getAssetContent(assetId: string, variant?: "preview" | "original", download?: boolean) {
  const qs = new URLSearchParams();
  if (variant && variant !== "original") qs.set("variant", variant);
  if (download) qs.set("download", "true");
  const url = `${apiBase}/assets/${assetId}/content${qs.toString() ? `?${qs.toString()}` : ""}`;
  return fetch(url);
}
