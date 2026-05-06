export interface MediaItem {
  name: string;
  type: "image" | "video";
  width: number;
  height: number;
  mtime: number;
  url: string;
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
