import { useState, useEffect, useCallback } from "react";
import { JobCard } from "./components/JobCard";
import { LoraTrainingCard } from "./components/LoraTrainingCard";
import { LoraCheckpointsCard } from "./components/LoraCheckpointsCard";
import type { JobItem, LoraCheckpoint, LoraTrainingStatus, MediaItem } from "./types";

export default function App() {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [training, setTraining] = useState<LoraTrainingStatus | null>(null);
  const [checkpoints, setCheckpoints] = useState<LoraCheckpoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!hasLoadedOnce) setLoading(true);
    try {
      const [listingRes, jobsRes, trainingRes, checkpointsRes] = await Promise.all([
        fetch("/api/listing"),
        fetch("/api/jobs"),
        fetch("/api/lora-training/status"),
        fetch("/api/lora-training/checkpoints"),
      ]);
      const listing = await listingRes.json();
      const jobData = await jobsRes.json();
      const trainingData = await trainingRes.json();
      const checkpointsData = await checkpointsRes.json();
      setItems(listing.images || []);
      setJobs(jobData.jobs || []);
      setTraining(trainingData.ok ? trainingData : null);
      setCheckpoints(checkpointsData.checkpoints || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
      setHasLoadedOnce(true);
    }
  }, [hasLoadedOnce]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, 3000);
    return () => window.clearInterval(id);
  }, [load]);

  const hasContent = jobs.length > 0 || items.length > 0;

  return (
    <div className="min-h-screen bg-black text-white">
      <header className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Nemoflix AMD Gallery</h1>
          <p className="text-xs text-gray-500 mt-1">Live from the MI300X droplet</p>
        </div>
        <div className="text-sm text-gray-500">
          {jobs.length > 0 && <span className="text-amber-400 mr-3">{jobs.length} generating</span>}
          <span>{items.length} media</span>
        </div>
      </header>

      <main className="p-6">
        <LoraTrainingCard training={training} />
        <LoraCheckpointsCard checkpoints={checkpoints} />

        {loading && !hasLoadedOnce && !hasContent ? (
          <p className="text-gray-500">Loading...</p>
        ) : !hasContent ? (
          <p className="text-gray-500">No media yet.</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {jobs.map((job) => (
              <JobCard key={job.prompt_id} job={job} />
            ))}

            {items.map((item) => (
              <div
                key={item.url}
                onClick={() => setSelected(item.url)}
                className="cursor-pointer rounded-lg overflow-hidden border border-gray-800 hover:border-rose-600 transition aspect-video bg-gray-900 relative group"
              >
                {item.type === "video" ? (
                  <video
                    src={item.url}
                    className="w-full h-full object-cover"
                    preload="metadata"
                    muted
                  />
                ) : (
                  <img
                    src={item.url}
                    alt={item.name}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                )}
                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent p-2 opacity-0 group-hover:opacity-100 transition">
                  <p className="text-xs truncate">{item.name}</p>
                </div>
                {item.type === "video" && (
                  <div className="absolute top-2 right-2 bg-black/60 text-white text-[10px] px-1.5 py-0.5 rounded">
                    VIDEO
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      {selected && (
        <div
          className="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4"
          onClick={() => setSelected(null)}
        >
          <div className="max-w-full max-h-full" onClick={(e) => e.stopPropagation()}>
            {selected.endsWith(".mp4") || selected.endsWith(".webm") ? (
              <video src={selected} controls autoPlay className="max-w-full max-h-[90vh] rounded" />
            ) : (
              <img src={selected} alt="" className="max-w-full max-h-[90vh] rounded" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
