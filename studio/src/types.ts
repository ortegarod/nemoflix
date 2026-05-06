export interface MediaItem {
  name: string;
  type: "image" | "video";
  width: number;
  height: number;
  mtime: number;
  url: string;
}

export interface LoraTrainingStatus {
  ok: boolean;
  status: string;
  job_name?: string | null;
  current_step: number;
  total_steps: number;
  progress_percent?: number | null;
  loss?: number | null;
  lr?: number | null;
  elapsed?: string | null;
  eta?: string | null;
  seconds_per_step?: number | null;
  gpu_util?: number | null;
  vram_percent?: number | null;
  updated_at: string;
  error?: string | null;
}

export interface LoraCheckpoint {
  name: string;
  step?: number | null;
  path: string;
  size_bytes: number;
  modified_at: string;
}

export interface LoraCheckpointsResponse {
  ok: boolean;
  job_name: string;
  checkpoints: LoraCheckpoint[];
  count: number;
  updated_at: string;
}

export interface JobItem {
  prompt_id: string;
  status: "pending" | "running" | "unknown" | "completed" | "failed" | string;
  mode?: string;
  prompt?: string;
  created_at?: string;
  queue_position?: number | null;
  current_node?: string | null;
  step_value?: number;
  step_max?: number;
  nodes_finished?: number;
  nodes_total?: number;
  progress_percent?: number | null;
  error?: string;
}
