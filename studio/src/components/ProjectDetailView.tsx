import { useEffect, useMemo, useRef, useState } from "react";
import { Film, Image as ImageIcon, Video, Wand2, Plus, Save, Layers, Sparkles, Edit3, Play, ArrowLeft, Trash2, Clapperboard, Loader2 } from "lucide-react";
import type { JobItem, Project, Scene, Shot, ShotVersion, ProjectPhase } from "../types";

interface ProjectDetailViewProps {
  project: Project;
  scenes: Scene[];
  shots: Shot[];
  jobs: JobItem[];
  selectedSceneId: string | null;
  selectedShotId: string | null;
  onSelectScene: (id: string) => void;
  onSelectShot: (id: string | null) => void;
  onRefresh: () => Promise<void> | void;
  onBack: () => void;
  onDeleteScene: (sceneId: string) => Promise<void> | void;
  onDeleteShot: (shotId: string) => Promise<void> | void;
}

function mediaUrl(file: string | null | undefined): string | null {
  if (!file) return null;
  if (file.startsWith("/") || file.startsWith("http")) return file;
  return `/media/${file}`;
}

export function ProjectDetailView({
  project, scenes, shots, jobs,
  selectedSceneId, selectedShotId,
  onSelectScene, onSelectShot, onRefresh, onBack,
  onDeleteScene, onDeleteShot,
}: ProjectDetailViewProps) {
  // Derive real phase from shot data, not prop
  const phase = useMemo<ProjectPhase>(() => {
    if (shots.length === 0) return "outline";
    const anyImage = shots.some((s) => s.image_file);
    const anyVideo = shots.some((s) => s.video_file);
    if (anyVideo) return "animate";
    if (anyImage) return "generate";
    return "outline";
  }, [shots]);
  const [versions, setVersions] = useState<ShotVersion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [renderStatus, setRenderStatus] = useState<string>(() => String(project.metadata?.render_status ?? "none"));
  const [finalVideoUrl, setFinalVideoUrl] = useState<string | null>(() => {
    const v = project.metadata?.final_video;
    return typeof v === "string" ? `/media/${v}` : null;
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setRenderStatus(String(project.metadata?.render_status ?? "none"));
    const v = project.metadata?.final_video;
    setFinalVideoUrl(typeof v === "string" ? `/media/${v}` : null);
  }, [project.metadata]);

  useEffect(() => {
    if (renderStatus !== "rendering") {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${project.id}/render`);
        if (!res.ok) return;
        const data = await res.json();
        setRenderStatus(data.status ?? "none");
        if (data.final_video_url) setFinalVideoUrl(data.final_video_url);
        if (data.status !== "rendering") {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
          if (data.status === "failed") setError(`Render failed: ${data.render_error ?? "unknown error"}`);
        }
      } catch { /* ignore */ }
    }, 3000);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [project.id, renderStatus]);

  async function handleRender() {
    if (renderStatus === "rendering") return;
    setError(null);
    setRenderStatus("rendering");
    try {
      const res = await fetch(`/api/projects/${project.id}/render`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `${res.status}`);
    } catch (e) {
      setRenderStatus("failed");
      setError(e instanceof Error ? e.message : "Render failed");
    }
  }

  const selectedScene = useMemo(() => scenes.find((s) => s.id === selectedSceneId) || null, [scenes, selectedSceneId]);
  const selectedShot = useMemo(() => shots.find((s) => s.id === selectedShotId) || null, [shots, selectedShotId]);
  const sceneShots = useMemo(() => shots.filter((s) => s.scene_id === selectedSceneId), [shots, selectedSceneId]);

  // Load versions for the focused shot
  useEffect(() => {
    if (!selectedShotId || !selectedSceneId) { setVersions([]); return; }
    let cancelled = false;
    fetch(`/api/projects/${project.id}/scenes/${selectedSceneId}/shots/${selectedShotId}/versions`)
      .then((r) => r.ok ? r.json() : { versions: [] })
      .then((data) => { if (!cancelled) setVersions(data.versions || []); })
      .catch(() => { if (!cancelled) setVersions([]); });
    return () => { cancelled = true; };
  }, [project.id, selectedSceneId, selectedShotId, shots]);

  const [saving, setSaving] = useState(false);

  // Look up the active job for a shot by matching prompt IDs
  function shotJob(shot: Shot): JobItem | undefined {
    return jobs.find((j) =>
      (shot.image_prompt_id && j.prompt_id === shot.image_prompt_id) ||
      (shot.video_prompt_id && j.prompt_id === shot.video_prompt_id)
    );
  }

  function isRendering(shot: Shot): boolean {
    const job = shotJob(shot);
    return (shot.status === 'rendering_image' || shot.status === 'animating') ||
      (!!job && (job.status === 'pending' || job.status === 'running'));
  }

  async function patchShot(shotId: string, patch: Partial<Shot>) {
    const shot = shots.find((s) => s.id === shotId);
    if (!shot) return;
    setSaving(true);
    try {
      const response = await fetch(`/api/projects/${project.id}/scenes/${shot.scene_id}/shots/${shotId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!response.ok) throw new Error(`Patch failed: ${response.status}`);
      await onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save shot");
    } finally {
      setSaving(false);
    }
  }

  async function addShot() {
    if (!selectedSceneId) return;
    setSaving(true);
    const next = sceneShots.length > 0 ? Math.max(...sceneShots.map((s) => s.shot_number)) + 1 : 1;
    try {
      const response = await fetch(`/api/projects/${project.id}/scenes/${selectedSceneId}/shots`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shot_number: next, description: "" }),
      });
      if (!response.ok) throw new Error(`Add shot failed: ${response.status}`);
      const created = await response.json();
      await onRefresh();
      onSelectShot(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add shot");
    } finally {
      setSaving(false);
    }
  }

  async function generateImage(shot: Shot) {
    if (isRendering(shot)) return;
    setSaving(true);
    try {
      const response = await fetch(`/api/projects/${project.id}/scenes/${shot.scene_id}/shots/${shot.id}/generate-image`, { method: "POST" });
      if (!response.ok) throw new Error(`Generate failed: ${response.status}`);
      await onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate image");
    } finally {
      setSaving(false);
    }
  }

  async function animateShot(shot: Shot) {
    if (isRendering(shot)) return;
    setSaving(true);
    try {
      const response = await fetch(`/api/projects/${project.id}/scenes/${shot.scene_id}/shots/${shot.id}/animate`, { method: "POST" });
      if (!response.ok) throw new Error(`Animate failed: ${response.status}`);
      await onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to animate");
    } finally {
      setSaving(false);
    }
  }

  async function selectVersion(version: ShotVersion) {
    if (!selectedShot) return;
    try {
      const response = await fetch(`/api/projects/${project.id}/scenes/${selectedShot.scene_id}/shots/${selectedShot.id}/versions/${version.id}/select`, { method: "POST" });
      if (!response.ok) throw new Error(`Select version failed: ${response.status}`);
      await onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to select version");
    }
  }

  return (
    <div className="h-full flex flex-col bg-black">
      {/* Top bar */}
      <div className="flex items-center justify-between gap-3 px-5 py-2.5 border-b border-gray-800/60 bg-gray-950/60 flex-shrink-0">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <button
            onClick={onBack}
            className="inline-flex items-center gap-1.5 rounded-xl border border-gray-800 bg-gray-900/50 hover:bg-gray-900 hover:border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition flex-shrink-0"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> All projects
          </button>
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-[0.22em] text-rose-400/70">Project</p>
            <h1 className="text-base font-semibold tracking-tight text-gray-100 truncate">{project.title}</h1>
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-[11px] flex-shrink-0">
          <PhaseChip phase={phase} />
          <span className="rounded-full border border-gray-800 bg-gray-900/50 px-2.5 py-1 text-gray-500 font-mono">{project.aspect_ratio}</span>
          {project.duration_seconds !== null && (
            <span className="rounded-full border border-gray-800 bg-gray-900/50 px-2.5 py-1 text-gray-500">{project.duration_seconds}s</span>
          )}
          <span className="rounded-full border border-gray-800 bg-gray-900/50 px-2.5 py-1 text-gray-500 uppercase tracking-wider">{project.status}</span>
          {phase === "animate" && renderStatus !== "completed" && (
            <button
              onClick={handleRender}
              disabled={renderStatus === "rendering"}
              className="inline-flex items-center gap-1.5 rounded-xl border border-violet-500/40 bg-violet-600/15 hover:bg-violet-600/25 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1.5 text-xs font-medium text-violet-100 transition"
            >
              {renderStatus === "rendering"
                ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Rendering…</>
                : <><Clapperboard className="w-3.5 h-3.5" /> Render final video</>
              }
            </button>
          )}
          {renderStatus === "completed" && finalVideoUrl && (
            <a
              href={finalVideoUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-600/15 hover:bg-emerald-600/25 px-3 py-1.5 text-xs font-medium text-emerald-100 transition"
            >
              <Play className="w-3.5 h-3.5" /> Watch final video
            </a>
          )}
        </div>
      </div>

      {/* Main split: center | right context editor */}
      <div className="flex-1 min-h-0 flex">
        {/* Center: shots in current scene */}
        <main className="flex-1 min-w-0 flex flex-col bg-gradient-to-b from-transparent via-transparent to-gray-950/30">
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-5xl mx-auto p-6 space-y-4">
              {selectedScene ? (
                <>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.2em] text-rose-400/70">Scene {selectedScene.scene_number}</p>
                      <h2 className="text-2xl font-bold tracking-tight mt-1">{selectedScene.title || "Untitled scene"}</h2>
                      {selectedScene.summary && (
                        <p className="text-sm text-gray-400 mt-2 max-w-2xl leading-relaxed">{selectedScene.summary}</p>
                      )}
                    </div>
                    <button
                      onClick={addShot}
                      disabled={saving}
                      className="inline-flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-600/10 hover:bg-rose-600/20 hover:border-rose-400/50 disabled:opacity-50 px-3 py-1.5 text-xs font-medium text-rose-100 transition flex-shrink-0"
                    >
                      <Plus className="w-3.5 h-3.5" /> {saving ? "Adding…" : "Add shot"}
                    </button>
                  </div>

                  {sceneShots.length === 0 ? (
                    <div className="rounded-2xl border border-gray-800/60 bg-gray-900/30 p-12 text-center">
                      <Film className="w-7 h-7 text-gray-600 mx-auto mb-2" />
                      <p className="text-sm text-gray-400">No shots in this scene yet.</p>
                      <p className="text-xs text-gray-600 mt-1.5">Add shots and write image prompts before generating.</p>
                    </div>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {sceneShots.map((shot) => (
                        <ShotCard
                          key={shot.id}
                          shot={shot}
                          phase={phase}
                          selected={shot.id === selectedShotId}
                          saving={saving}
                          onSelect={() => onSelectShot(shot.id)}
                          onGenerateImage={() => generateImage(shot)}
                          onAnimate={() => animateShot(shot)}
                          onDeleteShot={() => onDeleteShot(shot.id)}
                        />
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <OutlineCenter project={project} />
              )}
            </div>
          </div>

          {/* Bottom: shot version strip */}
          <div className="border-t border-gray-800/60 bg-gray-950/60 flex-shrink-0">
            <div className="px-4 py-2 flex items-center gap-3 overflow-x-auto">
              <span className="text-[10px] uppercase tracking-wider text-gray-500 font-medium flex-shrink-0">
                {selectedShot ? `S${selectedScene?.scene_number}·shot ${selectedShot.shot_number} versions` : "Versions"}
              </span>
              {!selectedShot && (
                <span className="text-[11px] text-gray-600">Select a shot to see its generated versions.</span>
              )}
              {selectedShot && versions.length === 0 && (
                <span className="text-[11px] text-gray-600">No versions yet. Generate to create one.</span>
              )}
              {versions.map((version) => {
                const url = mediaUrl(version.file);
                const isCurrent = selectedShot?.image_file === version.file || selectedShot?.video_file === version.file;
                return (
                  <button
                    key={version.id}
                    onClick={() => selectVersion(version)}
                    title={`v${version.version_number} · ${version.kind} · ${version.status}`}
                    className={`flex-shrink-0 relative rounded-lg overflow-hidden border transition ${isCurrent ? "border-rose-500/60 ring-1 ring-rose-500/40" : "border-gray-800 hover:border-gray-600"}`}
                  >
                    {url ? (
                      version.kind === "video" ? (
                        <video src={url} className="h-14 w-24 object-cover bg-black" muted />
                      ) : (
                        <img src={url} alt="" className="h-14 w-24 object-cover bg-black" />
                      )
                    ) : (
                      <div className="h-14 w-24 flex items-center justify-center bg-gray-900 text-[10px] text-gray-600">{version.status}</div>
                    )}
                    <span className={`absolute bottom-0.5 left-0.5 rounded px-1 text-[9px] font-mono ${isCurrent ? "bg-rose-600 text-white" : "bg-black/70 text-gray-300"}`}>v{version.version_number}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </main>

        {/* Right: context-aware editor — styled to match AppSidebar */}
        <aside className="w-[340px] flex-shrink-0 border-l border-gray-800/60 bg-gray-950/40 flex flex-col">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-800/40 flex-shrink-0">
            <span className="text-sm font-semibold text-gray-300 tracking-tight">
              {selectedShot ? `Shot ${selectedShot.shot_number}` : selectedScene ? `Scene ${selectedScene.scene_number}` : "Project"}
            </span>
            <span className="text-[10px] uppercase tracking-wider text-gray-600">{phase}</span>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
            {selectedShot ? (
              <ShotEditor
                shot={selectedShot}
                phase={phase}
                saving={saving}
                onPatch={(patch) => patchShot(selectedShot.id, patch)}
                onGenerate={() => generateImage(selectedShot)}
                onAnimate={() => animateShot(selectedShot)}
              />
            ) : selectedScene ? (
              <SceneSummary scene={selectedScene} />
            ) : (
              <ProjectSummary project={project} />
            )}
          </div>
        </aside>
      </div>

      {error && (
        <div className="absolute top-16 right-4 rounded-xl border border-red-500/30 bg-red-950/40 backdrop-blur px-3 py-2 text-xs text-red-300 max-w-sm cursor-pointer" onClick={() => setError(null)}>
          {error}
        </div>
      )}
    </div>
  );
}

function PhaseChip({ phase }: { phase: ProjectPhase }) {
  if (phase === "outline") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-700 bg-gray-900/60 px-2.5 py-1 text-gray-300">
        <Edit3 className="w-3 h-3" /> Outline
      </span>
    );
  }
  if (phase === "generate") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-500/40 bg-rose-600/15 px-2.5 py-1 text-rose-200">
        <Wand2 className="w-3 h-3" /> Generate
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-violet-500/40 bg-violet-600/15 px-2.5 py-1 text-violet-200">
      <Play className="w-3 h-3" /> Animate
    </span>
  );
}

function OutlineCenter({ project }: { project: Project }) {
  return (
    <div className="rounded-2xl border border-gray-800/60 bg-gray-900/30 p-12 text-center max-w-2xl mx-auto">
      <Layers className="w-9 h-9 text-gray-600 mx-auto mb-3" />
      <p className="text-base text-gray-300 font-medium">Outline phase</p>
      <p className="text-sm text-gray-500 mt-2 leading-relaxed max-w-md mx-auto">
        No scenes in <span className="text-gray-300">{project.title}</span> yet. Pitch your idea to your agent and it'll draft the structure here, or add the first scene yourself.
      </p>
    </div>
  );
}

function RemixCenter({ project, shots }: { project: Project; shots: Shot[] }) {
  const imageCount = shots.filter((s) => s.image_file).length;
  const videoCount = shots.filter((s) => s.video_file).length;
  const totalShots = shots.length;

  return (
    <div className="rounded-2xl border border-violet-500/20 bg-gradient-to-b from-violet-950/10 to-gray-950 p-8 text-center max-w-2xl mx-auto space-y-5">
      <div className="flex items-center justify-center gap-2">
        <Sparkles className="w-6 h-6 text-violet-400" />
        <p className="text-lg font-semibold text-violet-200">Remix Phase</p>
      </div>

      <div className="grid grid-cols-3 gap-3 text-[11px]">
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-2">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Images</p>
          <p className="text-violet-300 mt-0.5 font-mono text-sm">{imageCount}/{totalShots}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-2">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Videos</p>
          <p className="text-violet-300 mt-0.5 font-mono text-sm">{videoCount}/{totalShots}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-2">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Status</p>
          <p className="text-violet-300 mt-0.5 font-mono text-sm">{project.status}</p>
        </div>
      </div>

      <div className="space-y-3 text-left">
        <p className="text-xs text-gray-300 leading-relaxed">
          <strong className="text-violet-200">Remixing is editing.</strong> Change any prompt, hit regenerate, and iterate until it lands. Your agent can also edit prompts for you.
        </p>

        <div className="rounded-xl border border-gray-700/40 bg-gray-900/40 p-3 space-y-2">
          <p className="text-[11px] font-semibold text-gray-300">How Remix works:</p>
          {[
            { n: 1, title: "Pick a shot", body: "Click any shot card to select it. The right panel shows its prompts." },
            { n: 2, title: "Edit the prompt", body: "Change the image prompt or description in the right panel. Save your changes." },
            { n: 3, title: "Regenerate", body: "Click Generate or Re-image. The API runs the new prompt on AMD MI300X and returns a fresh image." },
            { n: 4, title: "Iterate", body: "Not quite right? Edit the prompt again and regenerate. Each run creates a new version you can compare." },
          ].map((step) => (
            <div key={step.n} className="flex gap-2.5">
              <div className="flex-shrink-0 w-5 h-5 rounded-md bg-violet-500/20 flex items-center justify-center mt-0.5">
                <span className="text-[10px] font-medium text-violet-400">{step.n}</span>
              </div>
              <div>
                <p className="text-[11px] text-gray-200">{step.title}</p>
                <p className="text-[10px] text-gray-500 leading-relaxed mt-0.5">{step.body}</p>
              </div>
            </div>
          ))}
        </div>

        <p className="text-[11px] text-gray-500 leading-relaxed">
          <strong className="text-gray-400">API:</strong> <code className="text-gray-500">POST /api/projects/{'{projectId}'}/scenes/{'{sceneId}'}/shots/{'{shotId}'}/generate-image</code> — regenerates with the current prompt. Or ask your agent: "Remix shot 2 with a darker mood."
        </p>
      </div>
    </div>
  );
}

function AnimateCenter({ project, shots }: { project: Project; shots: Shot[] }) {
  const imageCount = shots.filter((s) => s.image_file).length;
  const videoCount = shots.filter((s) => s.video_file).length;
  const totalShots = shots.length;

  return (
    <div className="rounded-2xl border border-violet-500/20 bg-gradient-to-b from-violet-950/10 to-gray-950 p-8 text-center max-w-2xl mx-auto space-y-5">
      <div className="flex items-center justify-center gap-2">
        <Play className="w-6 h-6 text-violet-400" />
        <p className="text-lg font-semibold text-violet-200">Animate Phase</p>
      </div>

      <div className="grid grid-cols-3 gap-3 text-[11px]">
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-2">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Images</p>
          <p className="text-violet-300 mt-0.5 font-mono text-sm">{imageCount}/{totalShots}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-2">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Videos</p>
          <p className="text-violet-300 mt-0.5 font-mono text-sm">{videoCount}/{totalShots}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-2">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Status</p>
          <p className="text-violet-300 mt-0.5 font-mono text-sm">{project.status}</p>
        </div>
      </div>

      <div className="space-y-3 text-left">
        <p className="text-xs text-gray-300 leading-relaxed">
          <strong className="text-violet-200">All images are generated.</strong> Now you can animate any shot into a video clip. Pick a shot and click Animate.
        </p>

        <div className="rounded-xl border border-gray-700/40 bg-gray-900/40 p-3 space-y-2">
          <p className="text-[11px] font-semibold text-gray-300">How Animate works:</p>
          {[
            { n: 1, title: "Pick a shot", body: "Click any shot card that has an image." },
            { n: 2, title: "Click Animate", body: "The API sends the image to Wan 2.2 I2V on AMD MI300X and returns a video clip." },
            { n: 3, title: "Iterate", body: "Don't like the video? Animate again — each run creates a new version." },
            { n: 4, title: "Select versions", body: "The bottom strip shows all versions. Click one to make it active." },
          ].map((step) => (
            <div key={step.n} className="flex gap-2.5">
              <div className="flex-shrink-0 w-5 h-5 rounded-md bg-violet-500/20 flex items-center justify-center mt-0.5">
                <span className="text-[10px] font-medium text-violet-400">{step.n}</span>
              </div>
              <div>
                <p className="text-[11px] text-gray-200">{step.title}</p>
                <p className="text-[10px] text-gray-500 leading-relaxed mt-0.5">{step.body}</p>
              </div>
            </div>
          ))}
        </div>

        <p className="text-[11px] text-gray-500 leading-relaxed">
          <strong className="text-gray-400">API:</strong> <code className="text-gray-500">POST /api/projects/{'{projectId}'}/scenes/{'{sceneId}'}/shots/{'{shotId}'}/animate</code> — returns <code className="text-gray-500">prompt_id</code> for tracking. Backend uses Wan 2.2 I2V on AMD MI300X.
        </p>
      </div>
    </div>
  );
}

interface ShotCardProps {
  shot: Shot;
  phase: ProjectPhase;
  selected: boolean;
  saving: boolean;
  onSelect: () => void;
  onGenerateImage: () => void;
  onAnimate: () => void;
  onDeleteShot: () => void;
}

function ShotCard({ shot, phase, selected, saving, onSelect, onGenerateImage, onAnimate, onDeleteShot }: ShotCardProps) {
  const imageUrl = mediaUrl(shot.image_file);
  const videoUrl = mediaUrl(shot.video_file);
  const showAnimate = !!imageUrl;
  // Only show video if there's no newer image version (re-image invalidates old video)
  const showVideo = !!videoUrl && shot.status !== 'image_ready';
  const rendering = shot.status === 'rendering_image' || shot.status === 'animating' || saving;
  return (
    <div
      onClick={onSelect}
      className={`rounded-xl border bg-gray-900/30 overflow-hidden cursor-pointer transition ${selected ? "border-rose-500/50 ring-1 ring-rose-500/30" : "border-gray-800/60 hover:border-gray-700"}`}
    >
      <div className="aspect-video bg-black flex items-center justify-center relative">
        {videoUrl ? (
          <video src={videoUrl} className="w-full h-full object-cover" muted loop autoPlay />
        ) : imageUrl ? (
          <img src={imageUrl} alt="" className="w-full h-full object-cover" />
        ) : (
          <div className="text-center text-gray-600">
            <ImageIcon className="w-6 h-6 mx-auto mb-1 opacity-50" />
            <p className="text-[10px] uppercase tracking-wider">No image</p>
          </div>
        )}
        <span className="absolute top-1.5 left-1.5 rounded-md bg-black/70 px-1.5 py-0.5 text-[10px] font-mono text-gray-200">
          shot {shot.shot_number}
        </span>
        {videoUrl && (
          <span className="absolute top-1.5 right-1.5 rounded-md bg-violet-600/80 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-white inline-flex items-center gap-1">
            <Video className="w-2.5 h-2.5" /> video
          </span>
        )}
      </div>
      <div className="p-2.5 space-y-1.5">
        <p className="text-[11px] text-gray-300 leading-relaxed line-clamp-2 min-h-[2.4em]">
          {shot.description || <span className="italic text-gray-600">no description</span>}
        </p>
        <div className="flex items-center gap-1.5 pt-1 border-t border-gray-800/40">
          {rendering ? (
            <div className="flex-1 rounded-lg border border-amber-800/30 bg-amber-950/20 px-2 py-1 text-[11px] text-amber-400 text-center">
              <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse mr-1.5 align-middle" />
              {shot.status === 'animating' ? 'Animating…' : 'Generating…'}
            </div>
          ) : phase === "outline" || !imageUrl ? (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); onGenerateImage(); }}
                className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-rose-500/30 bg-rose-600/10 hover:bg-rose-600/20 px-2 py-1 text-[11px] text-rose-100 transition"
              >
                <Wand2 className="w-3 h-3" /> {imageUrl ? "Regenerate" : "Generate"}
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteShot(); }}
                className="rounded-lg border border-gray-800 hover:bg-red-900/40 hover:border-red-800/50 px-1.5 py-1 text-[11px] text-gray-600 hover:text-red-400 transition"
                title="Delete shot"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={(e) => { e.stopPropagation(); onGenerateImage(); }}
                className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-700 bg-gray-900/60 hover:bg-gray-800 px-2 py-1 text-[11px] text-gray-300 transition"
              >
                <Wand2 className="w-3 h-3" /> Re-image
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onAnimate(); }}
                className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-violet-500/30 bg-violet-600/15 hover:bg-violet-600/25 px-2 py-1 text-[11px] text-violet-100 transition"
              >
                <Play className="w-3 h-3" /> Animate
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteShot(); }}
                className="rounded-lg border border-gray-800 hover:bg-red-900/40 hover:border-red-800/50 px-1.5 py-1 text-[11px] text-gray-600 hover:text-red-400 transition"
                title="Delete shot"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

interface ShotEditorProps {
  shot: Shot;
  phase: ProjectPhase;
  saving: boolean;
  onPatch: (patch: Partial<Shot>) => void;
  onGenerate: () => void;
  onAnimate: () => void;
}

function ShotEditor({ shot, phase, saving, onPatch, onGenerate, onAnimate }: ShotEditorProps) {
  const [draft, setDraft] = useState({
    subtitle: shot.subtitle || "",
    description: shot.description || "",
    image_prompt: shot.image_prompt || "",
    motion_prompt: shot.motion_prompt || "",
  });

  useEffect(() => {
    setDraft({
      subtitle: shot.subtitle || "",
      description: shot.description || "",
      image_prompt: shot.image_prompt || "",
      motion_prompt: shot.motion_prompt || "",
    });
  }, [shot.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty =
    draft.subtitle !== (shot.subtitle || "") ||
    draft.description !== (shot.description || "") ||
    draft.image_prompt !== (shot.image_prompt || "") ||
    draft.motion_prompt !== (shot.motion_prompt || "");

  return (
    <div className="space-y-4">
      <Field label="Subtitle" hint="Viewer-facing narration. Burned onto the final video.">
        <textarea
          value={draft.subtitle}
          onChange={(e) => setDraft((d) => ({ ...d, subtitle: e.target.value }))}
          rows={2}
          className="w-full rounded-lg bg-black/40 border border-gray-800 px-2.5 py-2 text-xs text-gray-200 focus:outline-none focus:border-rose-500/50 placeholder:text-gray-700 leading-relaxed"
          placeholder="The screen flickers to life at precisely 8:00 AM."
        />
      </Field>

      <Field label="Description" hint="What's in the frame, plain English.">
        <textarea
          value={draft.description}
          onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
          rows={3}
          className="w-full rounded-lg bg-black/40 border border-gray-800 px-2.5 py-2 text-xs text-gray-200 focus:outline-none focus:border-rose-500/50 placeholder:text-gray-700 leading-relaxed"
          placeholder="Wide shot of the workshop, neon glow on the floor."
        />
      </Field>

      <Field label="Image prompt" hint="Sent to image generation. Trigger words, lighting, lens, mood.">
        <textarea
          value={draft.image_prompt}
          onChange={(e) => setDraft((d) => ({ ...d, image_prompt: e.target.value }))}
          rows={4}
          className="w-full rounded-lg bg-black/40 border border-gray-800 px-2.5 py-2 text-xs text-gray-200 focus:outline-none focus:border-rose-500/50 placeholder:text-gray-700 leading-relaxed font-mono"
          placeholder="rigo, workshop interior, neon underglow, cinematic anamorphic lens, moody lighting"
        />
      </Field>

      <Field label="Motion prompt" hint="Camera move + motion for the animate step.">
        <textarea
          value={draft.motion_prompt}
          onChange={(e) => setDraft((d) => ({ ...d, motion_prompt: e.target.value }))}
          rows={3}
          className="w-full rounded-lg bg-black/40 border border-gray-800 px-2.5 py-2 text-xs text-gray-200 focus:outline-none focus:border-rose-500/50 placeholder:text-gray-700 leading-relaxed font-mono"
          placeholder="Slow push in, suit plates locking into place."
        />
      </Field>

      <div className="grid grid-cols-2 gap-2 text-[11px] text-gray-500">
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Status</p>
          <p className="text-gray-300 mt-0.5">{shot.status}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Duration</p>
          <p className="text-gray-300 mt-0.5">{shot.duration_seconds}s</p>
        </div>
      </div>

      <div className="space-y-2 pt-2 border-t border-gray-800/40">
        <button
          onClick={() => onPatch(draft)}
          disabled={!dirty || saving}
          className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl border border-gray-700 bg-gray-900/60 hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed px-3 py-2 text-xs font-medium text-gray-200 transition"
        >
          <Save className="w-3.5 h-3.5" /> {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
        </button>
        {(shot.status === 'rendering_image' || shot.status === 'animating') ? (
          <div className="rounded-xl border border-amber-800/30 bg-amber-950/20 px-3 py-2 text-xs text-amber-400 text-center font-medium">
            <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse mr-1.5 align-middle" />
            {shot.status === 'animating' ? 'Animating…' : 'Generating…'}
          </div>
        ) : phase === "outline" || !shot.image_file ? (
          <button
            onClick={() => { if (!saving) onGenerate(); }}
            disabled={saving}
            className="w-full inline-flex items-center justify-center gap-1.5 rounded-xl border border-rose-500/40 bg-rose-600/15 hover:bg-rose-600/25 disabled:opacity-50 px-3 py-2 text-xs font-medium text-rose-100 transition"
          >
            <Wand2 className="w-3.5 h-3.5" /> {shot.image_file ? "Regenerate image" : "Generate image"}
          </button>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => { if (!saving) onGenerate(); }}
              disabled={saving}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-gray-700 bg-gray-900/60 hover:bg-gray-800 disabled:opacity-50 px-3 py-2 text-xs font-medium text-gray-200 transition"
            >
              <Wand2 className="w-3.5 h-3.5" /> Re-image
            </button>
            <button
              onClick={() => { if (!saving) onAnimate(); }}
              disabled={saving}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-violet-500/40 bg-violet-600/15 hover:bg-violet-600/25 disabled:opacity-50 px-3 py-2 text-xs font-medium text-violet-100 transition"
            >
              <Play className="w-3.5 h-3.5" /> Animate
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div>
        <p className="text-[11px] font-medium text-gray-300">{label}</p>
        {hint && <p className="text-[10px] text-gray-600 leading-relaxed">{hint}</p>}
      </div>
      {children}
    </div>
  );
}

function ProjectSummary({ project }: { project: Project }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="text-[11px] font-medium text-gray-300">Title</p>
        <p className="text-sm text-gray-100 mt-0.5">{project.title}</p>
      </div>
      <div>
        <p className="text-[11px] font-medium text-gray-300">Description</p>
        <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{project.description || <span className="italic text-gray-600">no description</span>}</p>
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Aspect</p>
          <p className="text-gray-300 mt-0.5 font-mono">{project.aspect_ratio}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Duration</p>
          <p className="text-gray-300 mt-0.5">{project.duration_seconds ?? "—"}s</p>
        </div>
      </div>
      {project.characters.length > 0 && (
        <div>
          <p className="text-[11px] font-medium text-gray-300 mb-1">Cast</p>
          <div className="flex flex-wrap gap-1">
            {project.characters.map((id) => (
              <span key={id} className="inline-flex rounded-md border border-gray-800 bg-gray-900/40 px-2 py-0.5 text-[11px] text-gray-300 font-mono">{id}</span>
            ))}
          </div>
        </div>
      )}
      <p className="text-[11px] text-gray-600 leading-relaxed pt-2 border-t border-gray-800/40">
        Pick a scene from the Projects tab to start editing shots, or ask your agent to draft an outline.
      </p>
    </div>
  );
}

function SceneSummary({ scene }: { scene: Scene }) {
  return (
    <div className="space-y-3">
      <div>
        <p className="text-[11px] font-medium text-gray-300">Title</p>
        <p className="text-sm text-gray-100 mt-0.5">{scene.title || "Untitled scene"}</p>
      </div>
      <div>
        <p className="text-[11px] font-medium text-gray-300">Summary</p>
        <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{scene.summary || <span className="italic text-gray-600">no summary</span>}</p>
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Setting</p>
          <p className="text-gray-300 mt-0.5 capitalize">{scene.setting}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Weather</p>
          <p className="text-gray-300 mt-0.5 capitalize">{scene.weather}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Location</p>
          <p className="text-gray-300 mt-0.5">{scene.location || "—"}</p>
        </div>
        <div className="rounded-lg border border-gray-800 bg-gray-900/40 px-2.5 py-1.5">
          <p className="text-gray-600 text-[10px] uppercase tracking-wider">Time</p>
          <p className="text-gray-300 mt-0.5">{scene.time_of_day || "—"}</p>
        </div>
      </div>
      <p className="text-[11px] text-gray-600 leading-relaxed pt-2 border-t border-gray-800/40">
        Pick a shot in the center to start editing prompts.
      </p>
    </div>
  );
}
