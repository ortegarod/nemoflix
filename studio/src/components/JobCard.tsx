import type { JobItem } from "../types";

interface JobCardProps {
  job: JobItem;
}

function getProgress(job: JobItem): number | null {
  if (typeof job.progress_percent === "number") {
    return job.progress_percent;
  }

  if (job.step_max && job.step_max > 0) {
    return Math.round(((job.step_value || 0) / job.step_max) * 100);
  }

  return null;
}

export function JobCard({ job }: JobCardProps) {
  const progress = getProgress(job);
  const progressWidth = `${Math.max(3, progress ?? 3)}%`;

  return (
    <div className="rounded-lg overflow-hidden border border-amber-500/40 aspect-video bg-gray-950 relative p-4 flex flex-col justify-between">
      <div className="absolute inset-0 bg-gradient-to-br from-amber-500/10 via-transparent to-rose-600/10" />

      <div className="relative flex items-center justify-between gap-2 text-amber-300 text-xs font-medium uppercase tracking-wide">
        <span className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          {job.status === "running" ? "Generating" : job.status}
          {job.queue_position ? ` · Queue ${job.queue_position}` : ""}
        </span>
        {progress !== null && <span>{progress}%</span>}
      </div>

      <div className="relative space-y-2">
        <p className="text-sm font-medium line-clamp-2 text-white/90">
          {job.prompt || "Video generation job"}
        </p>

        <div className="space-y-1">
          <div className="h-1.5 rounded-full bg-gray-800 overflow-hidden">
            <div className="h-full bg-amber-400 transition-all" style={{ width: progressWidth }} />
          </div>

          <p className="text-[11px] text-gray-400 truncate">
            {job.current_node ? `Node ${job.current_node}` : "Waiting for Comfy progress event"}
            {job.step_max ? ` · step ${job.step_value || 0}/${job.step_max}` : ""}
            {job.nodes_total ? ` · nodes ${job.nodes_finished || 0}/${job.nodes_total}` : ""}
          </p>
        </div>
      </div>

      <p className="relative text-[10px] text-gray-500 font-mono truncate">{job.prompt_id}</p>
    </div>
  );
}
