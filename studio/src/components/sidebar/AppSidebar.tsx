import { useState, useEffect } from "react";
import { Info, Settings, Terminal, X, Cpu, Users, BookOpen, Search, Sparkles, Bot, Image, Box, Film } from "lucide-react";
import type { LoraCheckpoint, ProjectModeData } from "../../types";
import { GenerateTab } from "./GenerateTab";
import { NodesTab } from "./NodesTab";
import { ProjectSidebar } from "./ProjectSidebar";
import { ProjectsGuide } from "../ProjectsGuide";

export type SidebarTab = "generate" | "characters" | "agents" | "projects" | "guide" | "info" | "nodes" | "settings" | "dev";
export const SIDEBAR_WIDTH = 380;

interface CharacterSummary {
  id: string;
  name: string;
  trigger: string | null;
  kind: string | null;
  loras: Record<string, unknown>[];
  source_images: string[];
  defaults: Record<string, unknown>;
}

interface AppSidebarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  onClose: () => void;
  checkpoints: LoraCheckpoint[];
  onQueued?: () => void;
  onSelectCharacter?: (characterId: string) => void;
  projectMode?: ProjectModeData;
}

export function AppSidebar({ activeTab, onTabChange, onClose, checkpoints, onQueued, onSelectCharacter, projectMode }: AppSidebarProps) {
  const topTabs: { id: SidebarTab; icon: React.ReactNode; label: string; visible: boolean }[] = [
    { id: "generate", icon: <Image className="w-4 h-4" />, label: "Generate", visible: true },
    { id: "characters", icon: <Users className="w-4 h-4" />, label: "Characters & LoRA Training", visible: true },
    { id: "agents", icon: <Bot className="w-4 h-4" />, label: "Agents", visible: true },
    { id: "projects", icon: <Film className="w-4 h-4" />, label: "Projects", visible: true },
    { id: "guide", icon: <BookOpen className="w-4 h-4" />, label: "Guide", visible: true },
    { id: "info", icon: <Info className="w-4 h-4" />, label: "Info", visible: true },
    { id: "nodes", icon: <Cpu className="w-4 h-4" />, label: "Nodes", visible: true },
  ];

  const bottomTabs: { id: SidebarTab; icon: React.ReactNode; label: string; visible: boolean }[] = [
    { id: "dev", icon: <Terminal className="w-4 h-4" />, label: "Logs", visible: true },
    { id: "settings", icon: <Settings className="w-4 h-4" />, label: "Settings", visible: true },
  ];

  const visibleTopTabs = topTabs.filter((tab) => tab.visible);
  const visibleBottomTabs = bottomTabs.filter((tab) => tab.visible);
  const visibleTabs = [...visibleTopTabs, ...visibleBottomTabs];

  return (
    <div className="h-screen flex flex-shrink-0 border-r border-gray-800/60" style={{ width: `${SIDEBAR_WIDTH}px` }}>
      {/* Icon rail */}
      <div className="w-12 flex-shrink-0 bg-gray-950/60 border-r border-gray-800/40 flex flex-col items-center py-3 gap-1">
        {visibleTopTabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            title={tab.label}
            className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all relative group ${
              activeTab === tab.id
                ? "bg-rose-600/10 text-rose-400 ring-1 ring-rose-500/20"
                : "text-gray-600 hover:text-gray-300 hover:bg-gray-900/60"
            }`}
          >
            {tab.icon}
            {activeTab === tab.id && (
              <span className="absolute -left-1 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-rose-500 rounded-full" />
            )}
          </button>
        ))}

        <div className="mt-auto flex flex-col items-center gap-1">
          {visibleBottomTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              title={tab.label}
              className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all relative ${
                activeTab === tab.id
                  ? "bg-rose-600/10 text-rose-400 ring-1 ring-rose-500/20"
                  : "text-gray-600 hover:text-gray-300 hover:bg-gray-900/60"
              }`}
            >
              {tab.icon}
            </button>
          ))}
          <button
            onClick={onClose}
            title="Close sidebar"
            className="w-9 h-9 rounded-xl flex items-center justify-center text-gray-700 hover:text-gray-400 hover:bg-gray-900/60 transition mt-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Content panel */}
      <div className="flex-1 flex flex-col min-w-0 bg-gray-950/40 overflow-hidden">
        <div className="flex items-center px-4 py-2.5 border-b border-gray-800/40 flex-shrink-0">
          <span className="text-sm font-semibold text-gray-300 tracking-tight">
            {projectMode && activeTab === "projects" ? "Scenes" : visibleTabs.find((tab) => tab.id === activeTab)?.label}
          </span>
        </div>

        <div className="flex-1 min-h-0 overflow-hidden">
          {activeTab === "characters" && <CharactersTab onSelectCharacter={onSelectCharacter} />}
          {activeTab === "generate" && <GenerateTab checkpoints={checkpoints} onQueued={onQueued} />}
          {activeTab === "agents" && <AgentsTab />}
          {activeTab === "projects" && (projectMode ? <ProjectSidebar data={projectMode} onDeleteScene={(id) => projectMode.onDeleteScene(id)} /> : <ProjectsGuide compact />)}
          {activeTab === "guide" && <GuideTab />}
          {activeTab === "info" && <PlaceholderTab title="Info" body="Select media to inspect generated outputs, prompts, and metadata." />}
          {activeTab === "nodes" && <NodesTab />}
          {activeTab === "settings" && <PlaceholderTab title="Settings" body="Configure generation, training, and character workflow settings." />}
          {activeTab === "dev" && <PlaceholderTab title="Logs" body="Recent backend and generation events." />}
        </div>
      </div>
    </div>
  );
}

function CharactersTab({ onSelectCharacter }: { onSelectCharacter?: (characterId: string) => void }) {
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/characters")
      .then((r) => r.json())
      .then((d) => setCharacters(d.characters || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
      <div className="h-full overflow-y-auto p-4 space-y-4">
      {/* Character cards first — your owned assets */}
      <div className="rounded-xl border border-gray-800/60 bg-gray-900/30 p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-semibold text-gray-300">Your character assets</p>
          <span className="text-[10px] uppercase tracking-wider text-emerald-300/80 border border-emerald-500/20 bg-emerald-500/5 rounded-full px-2 py-0.5">Owned</span>
        </div>
        <p className="text-[11px] text-gray-500 leading-relaxed">
          These are characters you created or own the rights to use. Each one is backed by a fine-tuned LoRA trained on AMD MI300X.
        </p>
      </div>

      {loading && <p className="text-xs text-gray-500 py-2">Loading...</p>}
      {error && <p className="text-xs text-red-400 py-2">{error}</p>}
      {!loading && characters.length === 0 && (
        <div className="rounded-xl border border-gray-800/60 bg-gray-900/30 p-6 text-center">
          <Users className="w-5 h-5 text-gray-600 mx-auto mb-2" />
          <p className="text-xs text-gray-500">No characters registered yet.</p>
        </div>
      )}

      {characters.map((ch) => {
        const avatarUrl = ch.source_images.length > 0
          ? (ch.source_images[0].startsWith("/") ? ch.source_images[0] : `/media/${ch.source_images[0]}`)
          : null;

        return (
        <div
          key={ch.id}
          className="rounded-xl border border-gray-800/60 bg-gray-900/30 hover:bg-gray-900/50 hover:border-gray-600 p-3.5 cursor-pointer transition-all group"
          onClick={() => onSelectCharacter?.(ch.id)}
        >
          <div className="flex items-center gap-3 mb-2.5">
            <div className="w-10 h-10 rounded-xl overflow-hidden flex-shrink-0 ring-1 ring-white/10">
              {avatarUrl ? (
                <img src={avatarUrl} alt={ch.name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full bg-gradient-to-br from-rose-500 to-amber-400 flex items-center justify-center">
                  <span className="text-xs font-bold text-white">{ch.name.charAt(0).toUpperCase()}</span>
                </div>
              )}
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-gray-200 truncate">{ch.name}</span>
                {ch.kind === "human" && (
                  <span className="text-[9px] uppercase tracking-wider text-blue-300/80 border border-blue-500/30 bg-blue-500/10 rounded-full px-1.5 py-0.5 flex-shrink-0">Human</span>
                )}
                {ch.kind === "agent" && (
                  <span className="text-[9px] uppercase tracking-wider text-violet-300/80 border border-violet-500/30 bg-violet-500/10 rounded-full px-1.5 py-0.5 flex-shrink-0">Agent</span>
                )}
              </div>
              <div className="flex items-center gap-2 text-[11px] mt-0.5">
                <span className="text-gray-600 font-mono">{ch.id}</span>
                {ch.loras.length > 0 && (
                  <span className="text-emerald-400/60">{ch.loras.length} LoRA</span>
                )}
                <span className="text-[10px] uppercase tracking-wider text-emerald-300/80 border border-emerald-500/20 bg-emerald-500/5 rounded-full px-1.5 py-0.5">Owned</span>
              </div>
            </div>
          </div>

          <div className="pt-2 border-t border-gray-800/40">
            <p className="text-[10px] text-gray-500">
              Available for your agent to use in generated images and videos.
            </p>
          </div>
        </div>
        );
      })}

      {/* Training workflow below the character card */}
      <CreateCharacterWorkflow />

      <div className="pt-2 border-t border-gray-800/40">
        <a
          href="#"
          className="w-full rounded-xl border border-gray-700/60 hover:border-gray-500 bg-gray-900/40 px-4 py-2 text-xs text-gray-400 hover:text-gray-200 transition flex items-center justify-center gap-2"
          onClick={(e) => { e.preventDefault(); }}
        >
          <Search className="w-3.5 h-3.5" />
          Browse community characters
          <span className="text-[10px] text-gray-600 ml-1">coming soon</span>
        </a>
      </div>
    </div>
  );
}

function CreateCharacterWorkflow() {
  return (
    <div className="rounded-2xl border border-rose-600/20 bg-gradient-to-b from-rose-950/10 to-gray-950 p-4 space-y-4">
      <div className="flex items-center gap-2">
        <Box className="w-4 h-4 text-rose-400" />
        <span className="text-xs font-semibold text-rose-300 uppercase tracking-wider">LoRA Fine-tuning</span>
        <span className="text-[10px] uppercase tracking-wider text-amber-300/80 border border-amber-500/20 bg-amber-500/5 rounded-full px-2 py-0.5 ml-auto">AMD MI300X</span>
      </div>

      <p className="text-xs text-gray-300 leading-relaxed">
        <strong className="text-rose-200">Train your own character LoRA in ~90 minutes on AMD MI300X.</strong> Once fine-tuned, your AI agent can generate consistent images and videos with your face — every single time.
      </p>

      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
        <p className="text-[11px] font-semibold text-amber-300 flex items-center gap-1.5 mb-1">
          <Cpu className="w-3.5 h-3.5" />
          AMD MI300X — 192 GB VRAM
        </p>
        <p className="text-[11px] text-amber-200/70 leading-relaxed">
          Fine-tuning runs on AMD's flagship GPU via ROCm. No CUDA required. Train a Flux2 LoRA in ~90 minutes, then generate images and videos immediately.
        </p>
      </div>

      <div className="rounded-xl border border-gray-700/40 bg-gray-900/40 p-3">
        <p className="text-[11px] font-semibold text-gray-300 flex items-center gap-1.5 mb-2">
          <Terminal className="w-3.5 h-3.5 text-rose-400" />
          Tell your AI agent:
        </p>
        <p className="text-[11px] text-gray-400 leading-relaxed">
          "Create a character for me. Upload my reference images, register the character, start a LoRA fine-tune on AMD MI300X, and let me know when it's ready to use."
        </p>
      </div>

      <div className="space-y-2.5">
        <p className="text-[11px] font-medium text-gray-400">How it works:</p>
        {[
          { n: 1, title: "Upload your images", body: "5-20 reference photos. Different angles and lighting work best. Your agent can even generate variations to build a dataset." },
          { n: 2, title: "Register your character", body: "A character record with a unique trigger word — this is how the agent references your identity in every generation." },
          { n: 3, title: "Fine-tune on AMD MI300X", body: "Training a Flux2 LoRA on 192 GB MI300X VRAM via ROCm. Takes about 90 minutes. Your agent monitors progress and notifies you when done.", highlight: true },
          { n: 4, title: "Generate consistently", body: 'Your character appears in the registry. From then on, just say "generate a shot with [character name] doing X" — your agent handles the rest.' },
        ].map((step) => (
          <div key={step.n} className="flex gap-2.5">
            <div className={`flex-shrink-0 w-5 h-5 rounded-md flex items-center justify-center mt-0.5 ${step.highlight ? "bg-amber-500/20" : "bg-gray-800"}`}>
              <span className={`text-[10px] font-medium ${step.highlight ? "text-amber-400" : "text-gray-500"}`}>{step.n}</span>
            </div>
            <div>
              <p className={`text-[11px] ${step.highlight ? "text-amber-300 font-medium" : "text-gray-200"}`}>{step.title}</p>
              <p className="text-[10px] text-gray-500 leading-relaxed mt-0.5">{step.body}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="pt-1 border-t border-gray-800/40">
        <p className="text-[10px] text-gray-600">
          Your agent knows the API. It uses <code className="text-gray-500">/api/characters</code> to register, <code className="text-gray-500">/api/lora-training</code> to fine-tune, and the Guide tab has all the curl commands.
        </p>
      </div>
    </div>
  );
}

function GuideTab() {
  const apiRoot = typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:8190";
  const examples = [
    { label: "List characters", cmd: `curl ${apiRoot}/api/characters` },
    { label: "Create character", cmd: `curl -X POST ${apiRoot}/api/characters \\
  -H "Content-Type: application/json" \\
  -d '{"id":"my-char","name":"My Character","trigger":"MyTrigger"}'` },
    { label: "Create project", cmd: `curl -X POST ${apiRoot}/api/projects \\
  -H "Content-Type: application/json" \\
  -d '{"title":"My First Short","content":"A brief story...","characters":["rigo"]}'` },
    { label: "Add scene to project", cmd: `curl -X POST ${apiRoot}/api/projects/<prj_id>/scenes \\
  -H "Content-Type: application/json" \\
  -d '{"scene_number":1,"heading":"INT.-DAY","summary":"Scene summary"}'` },
    { label: "Add shot to scene", cmd: `curl -X POST ${apiRoot}/api/projects/<prj_id>/scenes/<scn_id>/shots \\
  -H "Content-Type: application/json" \\
  -d '{"shot_number":1,"description":"Visual shot description","motion_prompt":"Camera push in","duration_seconds":4}'` },
    { label: "Generate shot image", cmd: `curl -X POST ${apiRoot}/api/projects/<prj_id>/scenes/<scn_id>/shots/<sht_id>/generate-image` },
    { label: "Animate shot", cmd: `curl -X POST ${apiRoot}/api/projects/<prj_id>/scenes/<scn_id>/shots/<sht_id>/animate` },
    { label: "View project", cmd: `curl ${apiRoot}/api/projects/<prj_id>` },
    { label: "Raw image generation", cmd: `curl -X POST ${apiRoot}/api/image/generate \\
  -H "Content-Type: application/json" \\
  -d '{"character":"rigo","prompt":"studio portrait"}'` },
    { label: "Raw video generation", cmd: `curl -X POST ${apiRoot}/api/video/generate \\
  -H "Content-Type: application/json" \\
  -d '{"character":"rigo","prompt":"walks forward","width":1024,"height":1024,"length":41}'` },
  ];

  return (
    <div className="h-full overflow-y-auto p-4 space-y-3">
      <p className="text-xs text-gray-500 leading-relaxed">
        Paste these into a terminal or send them to your agent. Replace <code className="text-gray-400">&lt;prj_id&gt;</code> / <code className="text-gray-400">&lt;scn_id&gt;</code> / <code className="text-gray-400">&lt;sht_id&gt;</code> with actual IDs.
      </p>
      {examples.map((ex) => (
        <div key={ex.label} className="space-y-1">
          <p className="text-[11px] font-medium text-gray-400">{ex.label}</p>
          <pre className="text-[11px] bg-black/40 text-gray-300 rounded-xl p-2.5 overflow-x-auto leading-relaxed whitespace-pre-wrap break-all border border-gray-800/60 font-mono">{ex.cmd}</pre>
        </div>
      ))}
    </div>
  );
}

function AgentsTab() {
  const capabilities = [
    "Create and manage agent profiles",
    "Register owned character assets",
    "Start image and video generation jobs",
    "Build project scenes and shots through the API",
    "Route work to configured GPU nodes",
    "Launch LoRA training with ai-toolkit",
  ];

  const workflow = [
    {
      n: "01",
      title: "Tell the agent what to make",
      body: "Use plain language instead of filling out every workflow setting yourself.",
    },
    {
      n: "02",
      title: "Agent chooses the right workflow",
      body: "Image, video, character creation, project planning, or LoRA training should be selected automatically.",
    },
    {
      n: "03",
      title: "Nemoflix runs the job",
      body: "The backend handles API calls, configured GPU nodes, output paths, and job tracking.",
    },
    {
      n: "04",
      title: "Review and continue",
      body: "Generated assets appear in the Studio so the agent and human can iterate together.",
    },
  ];

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4">
      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-violet-400" />
          <h2 className="text-sm font-semibold text-gray-200">AI Agents</h2>
          <span className="text-[10px] uppercase tracking-wider text-amber-300/80 border border-amber-500/20 bg-amber-500/5 rounded-full px-2 py-0.5 ml-auto">Coming soon</span>
        </div>
        <p className="text-xs text-gray-500 leading-relaxed">
          Nemoflix is designed for AI agents that create media, manage characters, generate scenes, and publish work through an API-first studio.
        </p>
      </section>

      <div className="rounded-2xl border border-violet-600/20 bg-gradient-to-b from-violet-950/10 to-gray-950 p-4 space-y-3">
        <p className="text-xs font-semibold text-violet-300 uppercase tracking-wider">How agents use Nemoflix</p>
        <div className="space-y-3">
          {workflow.map((step) => (
            <div key={step.n} className="flex gap-3">
              <div className="flex-shrink-0 w-7 h-7 rounded-lg bg-gray-900 border border-gray-800 flex items-center justify-center">
                <span className="text-[10px] font-medium text-gray-500">{step.n}</span>
              </div>
              <div>
                <p className="text-xs text-gray-200">{step.title}</p>
                <p className="text-[11px] text-gray-500 leading-relaxed mt-0.5">{step.body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-gray-800/60 bg-gray-900/30 p-3 space-y-3">
        <p className="text-[11px] font-semibold text-gray-300">Planned capabilities</p>
        <div className="space-y-2">
          {capabilities.map((item) => (
            <div key={item} className="flex gap-2 text-[11px] text-gray-500">
              <span className="mt-1 w-1.5 h-1.5 rounded-full bg-violet-400/60 flex-shrink-0" />
              <span>{item}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-gray-800/60 bg-gray-900/30 p-3 space-y-2">
        <p className="text-[11px] font-semibold text-gray-300">Backend direction</p>
        <p className="text-[11px] text-gray-500 leading-relaxed">
          The agent endpoint should eventually execute real Nemoflix tools behind the scenes: character lookup, generation queueing, project updates, node checks, and training jobs.
        </p>
      </div>
    </div>
  );
}

function PlaceholderTab({ title, body }: { title: string; body: string }) {
  return (
    <div className="p-4 space-y-2 overflow-y-auto h-full">
      <h3 className="text-xs font-bold uppercase tracking-widest text-gray-600">{title}</h3>
      <p className="text-sm text-gray-500 leading-relaxed">{body}</p>
    </div>
  );
}
