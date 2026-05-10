import { useEffect, useState } from "react";
import { ArrowLeft, Film, Play, Download, Trash2 } from "lucide-react";

interface FilmItem {
  id: string;
  render_number: number;
  final_video_url: string | null;
  created_at: string;
  status: string;
}

interface Project {
  id: string;
  title: string;
  aspect_ratio: string;
}

interface ProjectFilmsViewProps {
  projectId: string;
  onBack: () => void;
}

export function ProjectFilmsView({ projectId, onBack }: ProjectFilmsViewProps) {
  const [project, setProject] = useState<Project | null>(null);
  const [films, setFilms] = useState<FilmItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [projectRes, filmRes] = await Promise.all([
        fetch(`/api/projects/${projectId}`),
        fetch(`/api/projects/${projectId}/render`),
      ]);
      if (!projectRes.ok) throw new Error(`Project ${projectRes.status}`);
      if (!filmRes.ok) throw new Error(`Films ${filmRes.status}`);
      const projectData = await projectRes.json();
      const filmData = await filmRes.json();
      setProject(projectData.project);
      setFilms(filmData.renders || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [projectId]);

  async function deleteFilm(filmId: string) {
    try {
      const res = await fetch(`/api/projects/${projectId}/renders/${filmId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Delete failed");
      setFilms((prev) => prev.filter((f) => f.id !== filmId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-black">
        <p className="text-sm text-gray-500">Loading films…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center bg-black">
        <p className="text-sm text-red-400">{error}</p>
      </div>
    );
  }

  const ar = project?.aspect_ratio ?? "9:16";
  const aspectClass = ar === "16:9" ? "aspect-[16/9]" : ar === "1:1" ? "aspect-square" : "aspect-[9/16]";
  const gridClass = ar === "16:9"
    ? "grid gap-6 sm:grid-cols-2 max-w-4xl mx-auto"
    : ar === "1:1"
    ? "grid gap-4 sm:grid-cols-2 lg:grid-cols-3 max-w-3xl mx-auto"
    : "grid gap-4 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 max-w-3xl mx-auto";

  return (
    <div className="h-full flex flex-col bg-black">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-5 py-2.5 border-b border-gray-800/60 bg-gray-950/60 flex-shrink-0">
        <button
          onClick={onBack}
          className="inline-flex items-center gap-1.5 rounded-xl border border-gray-800 bg-gray-900/50 hover:bg-gray-900 hover:border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to project
        </button>
        <div>
          <p className="text-[10px] uppercase tracking-[0.22em] text-rose-400/70">Films</p>
          <h1 className="text-base font-semibold tracking-tight text-gray-100">{project?.title}</h1>
        </div>
        <span className="ml-auto text-[11px] text-gray-500 font-mono">{films.length} film{films.length !== 1 ? "s" : ""}</span>
      </div>

      {/* Main */}
      <div className="flex-1 overflow-y-auto p-6">
        {films.length === 0 ? (
          <div className="text-center py-20">
            <Film className="w-8 h-8 text-gray-700 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No films yet.</p>
            <p className="text-xs text-gray-600 mt-1">Go back and hit Re-render to create one.</p>
          </div>
        ) : (
          <div className={gridClass}>
            {films.map((f) => (
              <div
                key={f.id}
                className="rounded-2xl border border-gray-800 bg-gray-900/40 overflow-hidden hover:border-gray-700 transition"
              >
                <div className={`${aspectClass} bg-black relative`}>
                  {f.final_video_url ? (
                    <video
                      src={f.final_video_url}
                      className="w-full h-full object-contain"
                      controls
                      preload="metadata"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-700">
                      <Film className="w-8 h-8" />
                    </div>
                  )}
                  <span className="absolute top-2 left-2 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-mono text-gray-200">
                    #{f.render_number}
                  </span>
                </div>
                <div className="p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-gray-400">{new Date(f.created_at).toLocaleString()}</span>
                    <span className={`text-[10px] uppercase px-1.5 py-0.5 rounded ${f.status === "completed" ? "bg-emerald-900/40 text-emerald-400" : "bg-amber-900/40 text-amber-400"}`}>
                      {f.status}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <a
                      href={f.final_video_url || "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-600/10 hover:bg-emerald-600/20 px-2 py-1.5 text-[11px] text-emerald-300 transition"
                    >
                      <Play className="w-3 h-3" /> Watch
                    </a>
                    <a
                      href={f.final_video_url || "#"}
                      download
                      className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-700 bg-gray-900/60 hover:bg-gray-800 px-2 py-1.5 text-[11px] text-gray-300 transition"
                    >
                      <Download className="w-3 h-3" /> Download
                    </a>
                    <button
                      onClick={() => deleteFilm(f.id)}
                      className="inline-flex items-center justify-center gap-1 rounded-lg border border-gray-800 hover:bg-red-900/30 hover:border-red-800/50 px-2 py-1.5 text-[11px] text-gray-600 hover:text-red-400 transition"
                      title="Delete film"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
