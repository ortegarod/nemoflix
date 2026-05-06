import type { LoraCheckpoint } from "../types";

interface LoraCheckpointsCardProps {
  checkpoints: LoraCheckpoint[];
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 MB";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatStep(step?: number | null): string {
  if (typeof step !== "number") return "unknown";
  return step.toLocaleString();
}

export function LoraCheckpointsCard({ checkpoints }: LoraCheckpointsCardProps) {
  if (checkpoints.length === 0) return null;

  return (
    <section className="mb-6 rounded-xl border border-cyan-500/30 bg-gray-950 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-semibold text-cyan-200 uppercase tracking-wide">LoRA Checkpoints</h2>
          <p className="text-xs text-gray-500 mt-1">Saved training weights available for testing</p>
        </div>
        <span className="text-xs font-mono text-cyan-300">{checkpoints.length} files</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        {checkpoints.map((checkpoint) => (
          <div key={checkpoint.path} className="rounded-lg border border-gray-800 bg-black/40 p-3">
            <div className="flex items-center justify-between gap-2 mb-2">
              <span className="text-xs text-gray-500 uppercase tracking-wide">Step</span>
              <span className="text-sm font-mono text-white">{formatStep(checkpoint.step)}</span>
            </div>
            <p className="text-xs text-gray-400 truncate" title={checkpoint.name}>{checkpoint.name}</p>
            <div className="mt-3 flex items-center justify-between text-[11px] text-gray-500 font-mono">
              <span>{formatBytes(checkpoint.size_bytes)}</span>
              <span>{new Date(checkpoint.modified_at).toLocaleTimeString()}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
