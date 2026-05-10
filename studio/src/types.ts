export interface MediaItem {
  name: string;
  type: "image" | "video";
  width: number;
  height: number;
  mtime: number;
  url: string;
  filename?: string;
  thumb?: string;
  prompt?: string | null;
  prompt_id?: string | null;
}

export interface LoraTrainingStatus {
  ok: boolean;
  status: string;
  running?: boolean;
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
  filename?: string;
  step?: number | null;
  path: string;
  size_bytes: number;
  modified_at: string;
  created_at?: string;
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
  status: "pending" | "running" | "completed" | "failed" | string;
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

export interface Project {
  id: string;
  title: string;
  description: string | null;
  aspect_ratio: string;
  duration_seconds: number | null;
  status: string;
  characters: string[];
  metadata: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export interface Scene {
  id: string;
  project_id: string;
  scene_number: number;
  title: string | null;
  setting: string;
  weather: string;
  summary: string | null;
  location: string | null;
  time_of_day: string | null;
  characters: string[];
  metadata: Record<string, unknown>;
}

export interface Shot {
  id: string;
  project_id: string;
  scene_id: string;
  shot_number: number;
  text: string | null;
  description: string | null;
  subtitle: string | null;
  voiceover: string | null;
  image_prompt: string | null;
  motion_prompt: string | null;
  characters: string[];
  duration_seconds: number;
  status: string;
  image_file: string | null;
  video_file: string | null;
  image_prompt_id: string | null;
  video_prompt_id: string | null;
  metadata: Record<string, unknown>;
}


export interface ShotVersion {
  id: string;
  project_id: string;
  scene_id: string;
  shot_id: string;
  version_number: number;
  kind: "image" | "video";
  status: string;
  prompt: string | null;
  file: string | null;
  prompt_id: string | null;
  metadata: Record<string, unknown>;
  created_at?: string;
}

export type ProjectPhase = "outline" | "generate" | "animate";

export interface ProjectModeData {
  project: Project;
  scenes: Scene[];
  shots: Shot[];
  selectedSceneId: string | null;
  selectedShotId: string | null;
  phase: ProjectPhase;
  onSelectScene: (sceneId: string) => void;
  onSelectShot: (shotId: string | null) => void;
  onBack: () => void;
  onRefresh: () => Promise<void> | void;
  onAddScene: () => Promise<void> | void;
  onDeleteScene: (sceneId: string) => Promise<void> | void;
  onDeleteShot: (shotId: string) => Promise<void> | void;
}
