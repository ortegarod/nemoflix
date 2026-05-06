import type { LoraTrainingStatus } from "../types";

interface LoraTrainingCardProps {
  training: LoraTrainingStatus | null;
}

function formatNumber(value?: number | null, digits = 2): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return value.toFixed(digits);
}

export function LoraTrainingCard({ training }: LoraTrainingCardProps) {
  if (!training || training.status === "missing_log") return null;

  const progress = training.progress_percent ?? 0;
  const progressWidth = `${Math.max(2, Math.min(100, progress))}%`;
  const statusLabel = training.status === "training" ? "Training" : training.status;

  return (
    <section className="mb-6 rounded-xl overflow-hidden border border-fuchsia-500/40 bg-gray-950 relative p-5">
      <div className="absolute inset-0 bg-gradient-to-br from-fuchsia-500/10 via-transparent to-cyan-500/10" />

      <div className="relative flex flex-col md:flex-row md:items-start md:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-fuchsia-300 text-xs font-semibold uppercase tracking-wide mb-2">
            <span className="inline-block w-2 h-2 rounded-full bg-fuchsia-400 animate-pulse" />
            LoRA Training · {statusLabel}
          </div>
          <h2 className="text-lg font-semibold text-white">{training.job_name || "Active LoRA job"}</h2>
          <p className="text-xs text-gray-400 mt-1">
            Step {training.current_step} / {training.total_steps}
            {training.eta ? ` · ETA ${training.eta}` : ""}
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm min-w-[320px]">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-gray-500">Loss</p>
            <p className="font-mono text-white">{formatNumber(training.loss, 4)}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-gray-500">GPU</p>
            <p className="font-mono text-white">{formatNumber(training.gpu_util, 0)}%</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-gray-500">VRAM</p>
            <p className="font-mono text-white">{formatNumber(training.vram_percent, 0)}%</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide text-gray-500">Step Time</p>
            <p className="font-mono text-white">{formatNumber(training.seconds_per_step, 2)}s</p>
          </div>
        </div>
      </div>

      <div className="relative mt-4 space-y-1">
        <div className="h-2 rounded-full bg-gray-800 overflow-hidden">
          <div className="h-full bg-gradient-to-r from-fuchsia-400 to-cyan-300 transition-all" style={{ width: progressWidth }} />
        </div>
        <div className="flex justify-between text-[11px] text-gray-400 font-mono">
          <span>{formatNumber(progress, 1)}%</span>
          <span>lr {training.lr ? training.lr.toExponential(1) : "--"}</span>
        </div>
      </div>
    </section>
  );
}
