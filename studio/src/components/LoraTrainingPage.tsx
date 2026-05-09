import React, { useCallback, useEffect, useState } from "react";
import { ChevronDown, Database, FolderPlus, X } from "lucide-react";
import { useApp } from "../App";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

interface Dataset {
  id: string;
  name: string;
  description: string | null;
  image_count: number | null;
  created_at: string;
}

interface Sample {
  name: string;
  step: number | null;
}

interface Checkpoint {
  name: string;
  step: number | null;
  path: string;
  size_bytes: number;
  modified_at: string;
}

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  if (status === "training" || status === "running") return "default";
  if (status === "completed") return "secondary";
  if (status === "failed") return "destructive";
  return "outline";
}

function formatDate(iso: string | undefined | null): string {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function LoraTrainingPage() {
  const ctx = useApp();
  const jobs = ctx.trainingJobs ?? [];
  const live = ctx.training;

  // Datasets
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);
  const [showAddDataset, setShowAddDataset] = useState(false);
  const [addDatasetId, setAddDatasetId] = useState("");
  const [addDatasetName, setAddDatasetName] = useState("");
  const [addDatasetDesc, setAddDatasetDesc] = useState("");
  const [addDatasetCount, setAddDatasetCount] = useState("");
  const [addDatasetSubmitting, setAddDatasetSubmitting] = useState(false);
  const [addDatasetError, setAddDatasetError] = useState<string | null>(null);

  const loadDatasets = useCallback(async () => {
    try {
      const res = await fetch("/api/lora-training/datasets");
      const data = await res.json();
      setDatasets(data.datasets || []);
    } catch {
      // ignore — non-critical
    } finally {
      setDatasetsLoading(false);
    }
  }, []);

  useEffect(() => { loadDatasets(); }, [loadDatasets]);

  const submitAddDataset = async () => {
    setAddDatasetError(null);
    setAddDatasetSubmitting(true);
    try {
      const res = await fetch("/api/lora-training/datasets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: addDatasetId,
          name: addDatasetName || addDatasetId,
          description: addDatasetDesc || undefined,
          image_count: addDatasetCount ? parseInt(addDatasetCount, 10) : undefined,
        }),
      });
      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail || "Failed to register dataset");
      }
      setAddDatasetId("");
      setAddDatasetName("");
      setAddDatasetDesc("");
      setAddDatasetCount("");
      setShowAddDataset(false);
      loadDatasets();
    } catch (e: any) {
      setAddDatasetError(e.message);
    } finally {
      setAddDatasetSubmitting(false);
    }
  };

  const mergedJobs = jobs.map((job: any) => {
    // Merge live ai-toolkit data into the matching job row so we get real
    // current_step / total_steps / loss / info. ai-toolkit uses "running"
    // while the DB-backed job list may say "training".
    if (live && live.job_name === job.job_name && (live.status === "running" || live.status === "training")) {
      return { ...job, ...live, _live: true };
    }
    // Job says running/training in the DB but ai-toolkit has no matching
    // live process. The job died or was abandoned — treat as failed.
    if (!live || live.job_name !== job.job_name) {
      if (job.status === "running" || job.status === "training") {
        return { ...job, status: "failed", _dead: true };
      }
    }
    return job;
  });

  const [showForm] = useState(true);
  const [formJobName, setFormJobName] = useState("");
  const [formTrigger, setFormTrigger] = useState("");
  const [formDataset, setFormDataset] = useState("rigo_flux2_lora_v1_dop");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const submitTraining = async () => {
    setSubmitError(null);
    setSubmitting(true);
    try {
      const res = await fetch("/api/lora-training/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_name: formJobName, trigger_word: formTrigger, dataset: formDataset }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to start training");
      setFormJobName("");
      setFormTrigger("");
      ctx.load();
    } catch (e: any) {
      setSubmitError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  // Cache samples + checkpoints per job so expanding one doesn't overwrite another.
  const [expandedData, setExpandedData] = useState<Map<string, { samples: Sample[]; checkpoints: Checkpoint[] }>>(new Map());
  const [loadingExpanded, setLoadingExpanded] = useState(false);

  const loadExpanded = useCallback(async (jobName: string) => {
    if (expandedData.has(jobName)) return; // already cached
    setLoadingExpanded(true);
    try {
      const [sRes, cRes] = await Promise.all([
        fetch(`/api/lora-training/samples?job_name=${jobName}`),
        fetch(`/api/lora-training/checkpoints?job_name=${jobName}`),
      ]);
      const sData = await sRes.json();
      const cData = await cRes.json();
      // ai-toolkit returns samples as flat file paths. Parse step number
      // from the filename pattern: ...__000000250_0.jpg
      const rawSamples: string[] = sData.samples || [];
      const parsedSamples: Sample[] = rawSamples.map((path) => {
        const basename = path.split("/").pop() ?? path;
        const match = basename.match(/__([0-9]+)_/);
        return { name: path, step: match ? Number(match[1]) : null };
      });
      setExpandedData(prev => {
        const next = new Map(prev);
        next.set(jobName, { samples: parsedSamples, checkpoints: cData.checkpoints || [] });
        return next;
      });
    } catch {
      setExpandedData(prev => {
        const next = new Map(prev);
        next.set(jobName, { samples: [], checkpoints: [] });
        return next;
      });
    } finally {
      setLoadingExpanded(false);
    }
  }, [expandedData]);

  const toggleJob = (jobName: string) => {
    if (expandedJob === jobName) {
      setExpandedJob(null);
    } else {
      setExpandedJob(jobName);
      loadExpanded(jobName);
    }
  };

  const completed = jobs.filter((j: any) => j.status === "completed").length;
  const running = jobs.filter((j: any) => j.status === "training" || j.status === "running").length;
  const failed = jobs.filter((j: any) => j.status === "failed").length;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Characters &amp; LoRA Training</h1>
          <p className="text-sm text-gray-500 mt-1">
            Train fine-tuned character LoRAs on AMD MI300X. Track all jobs, checkpoints, and stats.
          </p>
        </div>
      </div>

      {/* New training form */}
      {showForm && (
        <div className="rounded-xl border border-fuchsia-500/30 bg-gray-950 p-5 space-y-4">
          <h2 className="text-sm font-semibold text-fuchsia-300 uppercase tracking-wide">Start Training Job</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <label className="text-xs text-gray-400 uppercase tracking-wide">Job Name</label>
              <Input
                placeholder="e.g. rigo_v6_full"
                value={formJobName}
                onChange={e => setFormJobName(e.target.value)}
                className="bg-black/40 border-gray-700 text-white placeholder:text-gray-600"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-gray-400 uppercase tracking-wide">Trigger Word</label>
              <Input
                placeholder="e.g. Rigo"
                value={formTrigger}
                onChange={e => setFormTrigger(e.target.value)}
                className="bg-black/40 border-gray-700 text-white placeholder:text-gray-600"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs text-gray-400 uppercase tracking-wide">Dataset</label>
              {datasets.length > 0 ? (
                <select
                  value={formDataset}
                  onChange={e => setFormDataset(e.target.value)}
                  className="w-full rounded-md border border-gray-700 bg-black/40 px-3 py-2 text-sm text-white focus:outline-none focus:ring-1 focus:ring-fuchsia-500"
                >
                  {datasets.map(ds => (
                    <option key={ds.id} value={ds.id}>{ds.name}</option>
                  ))}
                </select>
              ) : (
                <Input
                  value={formDataset}
                  onChange={e => setFormDataset(e.target.value)}
                  className="bg-black/40 border-gray-700 text-white"
                />
              )}
            </div>
          </div>
          {submitError && <p className="text-sm text-rose-400">{submitError}</p>}
          <Button
            onClick={submitTraining}
            disabled={submitting || !formJobName || !formTrigger || !formDataset}
            className="bg-fuchsia-600 hover:bg-fuchsia-500 text-white"
          >
            {submitting ? "Starting…" : "Start Training"}
          </Button>
        </div>
      )}

      {/* Datasets */}
      <section className="rounded-xl border border-gray-800/60 bg-gray-950 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800/60 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Database className="w-4 h-4 text-fuchsia-400" />
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
              Training Datasets
              <span className="ml-2 text-xs font-mono text-gray-500">{datasets.length}</span>
            </h2>
          </div>
          <button
            onClick={() => setShowAddDataset(!showAddDataset)}
            className="flex items-center gap-1.5 rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-1.5 text-xs text-gray-300 hover:text-white hover:border-fuchsia-500/50 transition"
          >
            {showAddDataset ? <X className="w-3.5 h-3.5" /> : <FolderPlus className="w-3.5 h-3.5" />}
            {showAddDataset ? "Cancel" : "Add Dataset"}
          </button>
        </div>

        {showAddDataset && (
          <div className="px-5 py-4 border-b border-gray-800/40 bg-gray-900/20 space-y-3">
            <p className="text-xs text-gray-500">
              Register a dataset folder. Place your images at{" "}
              <code className="text-gray-400 bg-black/40 px-1 rounded">/root/nemoflix-training/datasets/&lt;id&gt;/</code>{" "}
              on the AMD node before starting a training job.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 uppercase tracking-wide">Folder ID *</label>
                <Input
                  placeholder="e.g. rigo_v2_photos"
                  value={addDatasetId}
                  onChange={e => setAddDatasetId(e.target.value)}
                  className="bg-black/40 border-gray-700 text-white text-sm placeholder:text-gray-600"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 uppercase tracking-wide">Display Name</label>
                <Input
                  placeholder="Optional display name"
                  value={addDatasetName}
                  onChange={e => setAddDatasetName(e.target.value)}
                  className="bg-black/40 border-gray-700 text-white text-sm placeholder:text-gray-600"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 uppercase tracking-wide">Description</label>
                <Input
                  placeholder="e.g. Rigo reference photos v2"
                  value={addDatasetDesc}
                  onChange={e => setAddDatasetDesc(e.target.value)}
                  className="bg-black/40 border-gray-700 text-white text-sm placeholder:text-gray-600"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[10px] text-gray-500 uppercase tracking-wide">Image Count</label>
                <Input
                  type="number"
                  placeholder="e.g. 25"
                  value={addDatasetCount}
                  onChange={e => setAddDatasetCount(e.target.value)}
                  className="bg-black/40 border-gray-700 text-white text-sm placeholder:text-gray-600"
                />
              </div>
            </div>
            {addDatasetError && <p className="text-sm text-rose-400">{addDatasetError}</p>}
            <Button
              onClick={submitAddDataset}
              disabled={addDatasetSubmitting || !addDatasetId}
              className="bg-fuchsia-600 hover:bg-fuchsia-500 text-white text-sm"
            >
              {addDatasetSubmitting ? "Registering…" : "Register Dataset"}
            </Button>
          </div>
        )}

        {datasetsLoading ? (
          <p className="text-xs text-gray-500 px-5 py-6">Loading…</p>
        ) : datasets.length === 0 ? (
          <p className="text-sm text-gray-500 py-8 text-center">
            No datasets registered. Add one above, then reference it when starting a training job.
          </p>
        ) : (
          <div className="divide-y divide-gray-800/40">
            {datasets.map(ds => (
              <div
                key={ds.id}
                className="px-5 py-3 flex items-center gap-4 hover:bg-gray-900/30 transition cursor-pointer"
                onClick={() => setFormDataset(ds.id)}
                title="Use in training form"
              >
                <div className="w-8 h-8 rounded-lg bg-fuchsia-900/30 border border-fuchsia-500/20 flex items-center justify-center flex-shrink-0">
                  <Database className="w-4 h-4 text-fuchsia-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-white truncate">{ds.name}</p>
                  <p className="text-[11px] text-gray-500 font-mono">{ds.id}{ds.description ? ` · ${ds.description}` : ""}</p>
                </div>
                {ds.image_count != null && (
                  <span className="text-[11px] text-gray-500 flex-shrink-0">{ds.image_count} images</span>
                )}
                <span className="text-[10px] text-gray-600 flex-shrink-0">{new Date(ds.created_at).toLocaleDateString()}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatBox label="Total Jobs" value={jobs.length} />
        <StatBox label="Running" value={running} color="text-fuchsia-400" />
        <StatBox label="Completed" value={completed} color="text-emerald-400" />
        <StatBox label="Failed" value={failed} color="text-rose-400" />
      </div>

      {/* Jobs table */}
      <section className="rounded-xl border border-gray-800/60 bg-gray-950 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800/60">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">
            Training Jobs
            <span className="ml-2 text-xs font-mono text-gray-500">{jobs.length}</span>
          </h2>
        </div>

        {jobs.length === 0 ? (
          <p className="text-sm text-gray-500 py-8 text-center">No training jobs yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-gray-800/60 hover:bg-transparent">
                <TableHead className="text-gray-500 text-xs uppercase tracking-wider w-10" />
                <TableHead className="text-gray-500 text-xs uppercase tracking-wider">Job</TableHead>
                <TableHead className="text-gray-500 text-xs uppercase tracking-wider">Status</TableHead>
                <TableHead className="text-gray-500 text-xs uppercase tracking-wider">Progress</TableHead>
                <TableHead className="text-gray-500 text-xs uppercase tracking-wider">Loss</TableHead>
                <TableHead className="text-gray-500 text-xs uppercase tracking-wider">Model</TableHead>
                <TableHead className="text-gray-500 text-xs uppercase tracking-wider text-right">Created</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mergedJobs.map((job: any) => {
                // ai-toolkit returns status="running" when actually training. The info
                // field is "Training" when steps are executing and "Initializing" when
                // models/latents are loading. Trust the live data, not hardcoded logic.
                const hasLiveProgress = job.current_step > 0 && job.total_steps > 0;
                const isTraining = (job.status === "training" || job.status === "running") && hasLiveProgress;
                const isInitializing = (job.status === "running" || job.status === "training") && !hasLiveProgress && job._live;
                const progress = hasLiveProgress
                  ? Math.round((job.current_step / job.total_steps) * 100)
                  : 0;
                const isExpanded = expandedJob === job.job_name;
                const isLoading = isExpanded && loadingExpanded && !expandedData.has(job.job_name);
                const jobData = expandedData.get(job.job_name);
                const samples = jobData?.samples ?? [];
                const checkpoints = jobData?.checkpoints ?? [];

                return (
                  <React.Fragment key={job.job_name}>
                    {/* Main row — clickable */}
                    <TableRow
                      key={job.job_name}
                      className={`border-gray-800/40 cursor-pointer transition-colors ${
                        isExpanded ? "bg-gray-900/60" : "hover:bg-gray-900/30"
                      }`}
                      onClick={() => toggleJob(job.job_name)}
                    >
                      <TableCell>
                        <ChevronDown
                          className={`w-4 h-4 text-gray-500 transition-transform ${
                            isExpanded ? "rotate-180" : ""
                          }`}
                        />
                      </TableCell>
                      <TableCell>
                        <div>
                          <p className="text-sm font-mono text-white truncate max-w-[200px]">{job.job_name}</p>
                          <p className="text-[11px] text-gray-500 mt-0.5">
                            {[job.trigger_word && `trigger: ${job.trigger_word}`, job.dataset].filter(Boolean).join(" · ")}
                          </p>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
                      </TableCell>
                      <TableCell className="min-w-[220px]">
                        {isTraining ? (
                          <div className="space-y-1.5">
                            <div className="flex items-center gap-2">
                              <Progress value={progress} className="h-1.5 flex-1 bg-gray-800 [&>div]:bg-fuchsia-500" />
                              <span className="text-[11px] font-mono text-fuchsia-400 tabular-nums">{progress}%</span>
                            </div>
                            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-gray-500 font-mono">
                              <span>Step {job.current_step}/{job.total_steps}</span>
                              {job.seconds_per_step ? <span>{job.seconds_per_step.toFixed(1)}s/step</span> : null}
                              {job.lr != null ? <span>lr {Number(job.lr).toExponential(1)}</span> : null}
                              {job.eta ? <span>{job.eta} left</span> : null}
                            </div>
                            {job.info && <div className="text-[10px] text-gray-500">ai-toolkit: {job.info}</div>}
                          </div>
                        ) : isInitializing ? (
                          <div className="flex items-center gap-2 text-sm text-amber-400">
                            <span className="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                            Initializing — loading models, caching latents…
                          </div>
                        ) : job.status === "completed" ? (
                          <div className="text-sm text-gray-400 font-mono space-y-0.5">
                            <p>{job.total_steps || 0} steps{job.elapsed ? ` · ${job.elapsed}` : ""}</p>
                            {job.loss != null ? <p className="text-xs text-gray-500">final loss {job.loss.toFixed(4)}</p> : null}
                          </div>
                        ) : job.status === "failed" ? (
                          <span className="text-xs text-gray-500">
                            {job._dead ? "Process died or was abandoned" : job.error || "Job failed"}
                          </span>
                        ) : (
                          <span className="text-sm text-gray-600">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <span className="text-sm font-mono text-white">
                          {job.loss != null ? job.loss.toFixed(4) : "—"}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="text-sm text-gray-400">{job.model || "—"}</span>
                      </TableCell>
                      <TableCell className="text-right">
                        <span className="text-sm text-gray-500 font-mono">{formatDate(job.created_at)}</span>
                      </TableCell>
                    </TableRow>

                    {/* Expanded sub-row — inline, directly under the clicked row */}
                    {isExpanded && (
                      <TableRow key={`${job.job_name}-expanded`} className="border-gray-800/40 bg-gray-900/40">
                        <TableCell colSpan={7} className="p-0">
                          {isLoading ? (
                            <div className="px-6 py-6 text-sm text-gray-500">Loading samples and checkpoints…</div>
                          ) : (
                            <div className="px-6 py-5 space-y-5">
                              {/* Samples */}
                              {samples.length > 0 && (
                                <div>
                                  <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
                                    Training Samples ({samples.length})
                                  </h4>
                                  <div className="flex gap-3 overflow-x-auto pb-2">
                                    {samples.map((s) => (
                                      <div
                                        key={s.name}
                                        className="flex-shrink-0 w-24 rounded-lg border border-gray-800 bg-black/40 overflow-hidden"
                                      >
                                        <img
                                          src={`/api/lora-training/sample-image?path=${encodeURIComponent(s.name)}`}
                                          alt={`Sample step ${s.step}`}
                                          className="w-full aspect-square object-cover"
                                        />
                                        <div className="px-1.5 py-1 text-[10px] text-gray-500 font-mono text-center">
                                          Step {s.step ?? "?"}
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {/* Checkpoints */}
                              {checkpoints.length > 0 && (
                                <div>
                                  <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
                                    Checkpoints ({checkpoints.length})
                                  </h4>
                                  <Table>
                                    <TableHeader>
                                      <TableRow className="border-gray-800/60 hover:bg-transparent">
                                        <TableHead className="text-gray-500 text-xs uppercase tracking-wider">Step</TableHead>
                                        <TableHead className="text-gray-500 text-xs uppercase tracking-wider">File</TableHead>
                                        <TableHead className="text-gray-500 text-xs uppercase tracking-wider text-right">Size</TableHead>
                                        <TableHead className="text-gray-500 text-xs uppercase tracking-wider text-right">Date</TableHead>
                                      </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                      {checkpoints.map((ck) => (
                                        <TableRow key={ck.name} className="border-gray-800/40 hover:bg-gray-900/30">
                                          <TableCell className="font-mono text-sm text-violet-300">{ck.step ?? "final"}</TableCell>
                                          <TableCell className="font-mono text-[11px] text-gray-400 max-w-[300px] truncate">{ck.name}</TableCell>
                                          <TableCell className="text-right font-mono text-sm text-gray-400">
                                            {(ck.size_bytes / 1024 / 1024).toFixed(0)} MB
                                          </TableCell>
                                          <TableCell className="text-right text-sm text-gray-500">
                                            {new Date(ck.modified_at).toLocaleDateString()}
                                          </TableCell>
                                        </TableRow>
                                      ))}
                                    </TableBody>
                                  </Table>
                                </div>
                              )}

                              {samples.length === 0 && checkpoints.length === 0 && (
                                <p className="text-sm text-gray-600 py-2">No samples or checkpoints for this job.</p>
                              )}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}
            </TableBody>
          </Table>
        )}
      </section>
    </div>
  );
}

function StatBox({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-black/40 p-3 text-center">
      <p className={`text-lg font-bold ${color || "text-white"}`}>{value}</p>
      <p className="text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
    </div>
  );
}
