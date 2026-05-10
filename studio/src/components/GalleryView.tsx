import { useMemo, useState, useCallback } from "react";
import { ArrowRight, Film, Image, Search, SlidersHorizontal, Video } from "lucide-react";
import { JobCard } from "./JobCard";
import { MediaTile } from "./MediaTile";
import { generateVideo } from "../api";
import type { JobItem, MediaItem } from "../types";

type Filter = "all" | "images" | "videos";

interface StudioViewProps {
  items: MediaItem[];
  jobs: JobItem[];
  loading: boolean;
  error: string | null;
  onOpen: (url: string) => void;
  onDelete: (item: MediaItem) => Promise<void> | void;
  onOpenProjects?: () => void;
}

function isVideo(item: MediaItem) {
  return item.type === "video" || item.url.endsWith(".mp4") || item.url.endsWith(".webm");
}

export function StudioView({ items, jobs, loading, error, onOpen, onDelete, onOpenProjects }: StudioViewProps) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [generatingVideo, setGeneratingVideo] = useState<Set<string>>(new Set());

  const handleGenerateVideo = useCallback(async (item: MediaItem, motionPrompt: string) => {
    const key = item.filename || item.url;
    setGeneratingVideo((prev) => new Set(prev).add(key));
    try {
      await generateVideo({
        image: item.filename || item.url.split("/").pop() || "",
        prompt: motionPrompt || undefined,
      });
    } catch (err) {
      console.error("I2V failed:", err);
    } finally {
      setGeneratingVideo((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  }, []);

  const imageCount = items.filter((item) => !isVideo(item)).length;
  const videoCount = items.length - imageCount;

  const visibleItems = useMemo(() => {
    const q = query.trim().toLowerCase();
    return items.filter((item) => {
      if (filter === "images" && isVideo(item)) return false;
      if (filter === "videos" && !isVideo(item)) return false;
      if (!q) return true;
      return [item.name, item.filename, item.prompt].some((value) => String(value || "").toLowerCase().includes(q));
    });
  }, [filter, items, query]);

  return (
    <div className="p-5 lg:p-7 space-y-6">
      <section className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-rose-400/70">Workspace</p>
          <h1 className="text-2xl font-bold tracking-tight mt-1">Studio</h1>
          <p className="text-sm text-gray-500 mt-2">Your gallery for quick image and video generation — freeform, no structure. Generate, browse, iterate.</p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs min-w-[260px]">
          <div className="rounded-xl border border-gray-800 bg-gray-900/40 px-3 py-2">
            <p className="text-gray-600">Total</p>
            <p className="text-lg font-semibold text-gray-200">{items.length}</p>
          </div>
          <div className="rounded-xl border border-gray-800 bg-gray-900/40 px-3 py-2">
            <p className="text-gray-600">Images</p>
            <p className="text-lg font-semibold text-gray-200">{imageCount}</p>
          </div>
          <div className="rounded-xl border border-gray-800 bg-gray-900/40 px-3 py-2">
            <p className="text-gray-600">Videos</p>
            <p className="text-lg font-semibold text-gray-200">{videoCount}</p>
          </div>
        </div>
      </section>

      <button
        onClick={onOpenProjects}
        className="group w-full rounded-2xl border border-violet-600/30 bg-gradient-to-r from-violet-950/30 via-indigo-950/20 to-gray-900/30 hover:border-violet-500/50 hover:from-violet-950/50 transition flex items-center gap-4 px-5 py-4 text-left"
      >
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-500 flex items-center justify-center shadow-lg shadow-violet-500/20 ring-1 ring-white/10 flex-shrink-0">
          <Film className="w-5 h-5 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-violet-100">Got a specific idea? Turn it into a Project.</p>
          <p className="text-xs text-gray-400 mt-1 leading-relaxed">
            Studio is great for quick shots. <span className="text-gray-300">Projects</span> are for finished pieces — outline scenes, plan shots, generate, animate, and stitch together a real video.
          </p>
        </div>
        <ArrowRight className="w-5 h-5 text-violet-400 group-hover:translate-x-1 transition flex-shrink-0" />
      </button>

      <section className="rounded-2xl border border-gray-800/60 bg-gray-950/50 p-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex gap-2">
          {[
            ["all", "All", SlidersHorizontal],
            ["images", "Images", Image],
            ["videos", "Videos", Video],
          ].map(([id, label, Icon]) => (
            <button
              key={id as string}
              onClick={() => setFilter(id as Filter)}
              className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition ${
                filter === id ? "bg-rose-600 text-white" : "bg-gray-900 text-gray-500 hover:text-gray-200"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label as string}
            </button>
          ))}
        </div>
        <label className="relative w-full lg:w-80">
          <Search className="w-4 h-4 text-gray-600 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search studio"
            className="w-full rounded-xl bg-black/40 border border-gray-800 pl-9 pr-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-rose-600 placeholder:text-gray-700"
          />
        </label>
      </section>

      {loading && items.length === 0 && jobs.length === 0 ? (
        <p className="text-gray-500">Loading...</p>
      ) : error ? (
        <div className="rounded-lg border border-red-900/60 bg-red-950/20 p-4 text-sm text-red-300">{error}</div>
      ) : jobs.length === 0 && visibleItems.length === 0 ? (
        <div className="rounded-2xl border border-gray-800/60 bg-gray-900/20 p-10 text-center">
          <Image className="w-8 h-8 text-gray-700 mx-auto mb-3" />
          <p className="text-sm text-gray-500">No media found.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
          {jobs.map((job) => <JobCard key={job.prompt_id} job={job} />)}
          {visibleItems.map((item) => (
            <MediaTile
              key={item.filename || item.url}
              item={item}
              onOpen={() => onOpen(item.url)}
              onDelete={onDelete}
              onGenerateVideo={handleGenerateVideo}
            />
          ))}
        </div>
      )}
    </div>
  );
}
