import type { Device, Health, Job, Memory, Observation, QueryResponse, QueryScope } from "@/types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}/api/v1${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: async (): Promise<Health> => {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  },
  devices: () => request<Device[]>("/devices"),
  device: (id: string) => request<Device>(`/devices/${encodeURIComponent(id)}`),
  jobs: () => request<Job[]>("/jobs"),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  memories: (scope: QueryScope = {}, limit = 200) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (scope.device_id) q.set("device_id", scope.device_id);
    if (scope.job_id) q.set("job_id", scope.job_id);
    return request<Memory[]>(`/memories?${q}`);
  },
  ignored: (scope: QueryScope) => {
    const q = new URLSearchParams({ status: "dismissed", limit: "100" });
    if (scope.device_id) q.set("device_id", scope.device_id);
    if (scope.job_id) q.set("job_id", scope.job_id);
    return request<Observation[]>(`/observations?${q}`);
  },
  query: (query: string, scope: QueryScope = {}) =>
    request<QueryResponse>("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, ...scope }),
    }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Job>("/jobs", { method: "POST", body: form });
  },
};

export const evidenceUrl = (path: string) => `${API_URL}${path}`;

/** Ask every polling view to refresh now (e.g. right after an upload). */
export const REFRESH_EVENT = "vm:refresh";
export const triggerRefresh = () => window.dispatchEvent(new Event(REFRESH_EVENT));
