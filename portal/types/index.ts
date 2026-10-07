export type DeviceStatus = "online" | "offline";

export interface Device {
  id: string;
  name: string;
  status: DeviceStatus;
  created_at: string;
  last_seen: string | null;
  memory_count: number;
  observation_count: number;
  pending_count: number;
  dismissed_count: number;
  failed_count: number;
  last_memory_at: string | null;
  stats: Record<string, number> | null;
}

export type JobStatus = "queued" | "processing" | "analyzing" | "completed" | "failed";

export interface Job {
  id: string;
  filename: string;
  status: JobStatus;
  progress: number;
  duration_s: number | null;
  observations_total: number;
  observations_done: number;
  memory_count: number;
  dismissed_count: number;
  stats: Record<string, number> | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface MemoryObject {
  name: string;
  action: string;
  location_before: string | null;
  location_after: string | null;
}

export interface Evidence {
  name: string; // before | mid | after
  url: string;
}

export interface Memory {
  id: string;
  observation_id: string;
  source: "device" | "upload";
  device_id: string | null;
  device_name: string | null;
  job_id: string | null;
  job_filename: string | null;
  timestamp: string;
  video_offset_s: number | null;
  event_type: string;
  summary: string;
  objects: MemoryObject[];
  location_before: string | null;
  location_after: string | null;
  confidence: number | null;
  evidence: Evidence[];
}

/** A raw event sent for analysis (used to show the ones the model ignored, with its reason). */
export interface Observation {
  id: string;
  source: "device" | "upload";
  device_id: string | null;
  job_id: string | null;
  timestamp: string;
  video_offset_s: number | null;
  type: "baseline" | "visual_change" | "activity";
  status: "pending" | "processed" | "dismissed" | "failed";
  result: { summary: string } | null;
  error: string | null;
  evidence: Evidence[];
}

export interface Health {
  ok: boolean;
  vision_base_url: string;
  model: {
    name: string;
    status: "checking" | "ready" | "downloading" | "unavailable" | "error" | "external";
    progress: number | null;
    message: string | null;
  };
}

export interface QueryScope {
  device_id?: string;
  job_id?: string;
}

export interface QueryResponse {
  answer: string;
  memories: Memory[];
  used_llm: boolean;
}
