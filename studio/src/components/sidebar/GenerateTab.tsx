import { useEffect, useMemo, useState } from "react";
import type { LoraCheckpoint } from "../../types";

interface GenerateTabProps {
  checkpoints: LoraCheckpoint[];
  onQueued?: () => void;
}

type GenerateMode = "image" | "t2v" | "i2v";

interface GenerateResponse {
  ok: boolean;
  prompt_id?: string | null;
  checkpoint?: string | null;
  lora_name?: string | null;
  mode?: string;
  node_errors?: Record<string, unknown> | null;
}

interface CharacterSummary {
  id: string;
  name: string;
  trigger: string | null;
  loras: { workflow?: string; name?: string; strength?: number }[];
  source_images: string[];
}

const DEFAULT_IMAGE_PROMPT =
  "Rigo, portrait in a sleek AI media studio, leaning one hand on a workstation beside glowing video timeline screens, calm confident expression, modern editorial photography, warm cinematic key light, 85mm lens, shallow depth of field, realistic skin texture and sharp facial detail.";
const DEFAULT_VIDEO_PROMPT =
  "cinematic motion, dramatic camera movement, atmospheric lighting, dynamic composition, polished short-form video style";

function checkpointLabel(checkpoint: LoraCheckpoint) {
  if (checkpoint.step == null) return `${checkpoint.name} · final`;
  return `${checkpoint.name} · step ${checkpoint.step.toLocaleString()}`;
}

function slugPrompt(prompt: string) {
  const slug = prompt
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 36);
  return slug || "generation";
}

function outputPrefix(mode: GenerateMode, prompt: string) {
  const bucket = mode === "image" ? "images" : "videos";
  return `${bucket}/${slugPrompt(prompt)}-${Date.now()}`;
}

export function GenerateTab({ checkpoints, onQueued }: GenerateTabProps) {
  const latestCheckpoint = useMemo(() => {
    const final = checkpoints.find((checkpoint) => checkpoint.step == null);
    return final?.name || checkpoints[checkpoints.length - 1]?.name || "latest";
  }, [checkpoints]);

  const [mode, setMode] = useState<GenerateMode>("image");
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [characterId, setCharacterId] = useState("none");
  const [checkpoint, setCheckpoint] = useState("base");
  const [prompt, setPrompt] = useState(DEFAULT_IMAGE_PROMPT);
  const [sourceImage, setSourceImage] = useState("");
  const [width, setWidth] = useState(1248);
  const [height, setHeight] = useState(832);
  const [steps, setSteps] = useState(20);
  const [guidance, setGuidance] = useState(4);
  const [loraStrength, setLoraStrength] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/characters")
      .then((response) => response.json())
      .then((data) => setCharacters(data.characters || []))
      .catch(() => setCharacters([]));
  }, []);

  const selectedCharacter = characters.find((character) => character.id === characterId);
  const selectedCharacterHasImageLora = Boolean(selectedCharacter?.loras?.some((lora) => lora.workflow === "flux2_lora"));

  function selectMode(nextMode: GenerateMode) {
    setMode(nextMode);
    setPrompt(nextMode === "image" ? DEFAULT_IMAGE_PROMPT : DEFAULT_VIDEO_PROMPT);
    setResult(null);
    setError(null);
  }

  async function submit() {
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt) {
      setError("Prompt is required.");
      return;
    }
    if (mode === "i2v" && !sourceImage.trim()) {
      setError("Image-to-video needs a source image path from the gallery, like images/example.png.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setResult(null);

    try {
      const filenamePrefix = outputPrefix(mode, cleanPrompt);
      const endpoint = mode === "image" ? "/api/image/generate" : "/api/video/generate";
      const useCharacter = characterId !== "none";
      const useCheckpoint = !useCharacter && checkpoint !== "base";
      const body = mode === "image"
        ? {
            workflow: "flux2_lora",
            character: useCharacter ? characterId : undefined,
            checkpoint: useCheckpoint ? (checkpoint || latestCheckpoint) : undefined,
            prompt: cleanPrompt,
            width,
            height,
            steps,
            guidance,
            lora_strength: loraStrength,
            filename_prefix: filenamePrefix,
            submit: true,
          }
        : {
            mode,
            character: useCharacter ? characterId : undefined,
            image: mode === "i2v" ? sourceImage.trim() : undefined,
            prompt: cleanPrompt,
            width,
            height,
            filename_prefix: filenamePrefix,
            submit: true,
          };

      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.detail || `${response.status}: failed to queue generation`);
      }

      setResult(data);
      onQueued?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  const characterPhrase = selectedCharacter ? ` using ${selectedCharacter.name}` : "";
  const agentInstruction = mode === "image"
    ? `Generate a new image${characterPhrase} from this idea.`
    : mode === "t2v"
      ? "Generate a short video from this idea."
      : "Animate this gallery image into a short video.";

  return (
    <div className="h-full overflow-y-auto p-4 space-y-5">
      <section className="rounded-2xl border border-rose-600/30 bg-gradient-to-b from-rose-950/25 to-gray-950/70 p-4 space-y-3 shadow-lg shadow-rose-950/10">
        <h2 className="text-lg font-semibold">Tell your agent what to make</h2>
        <p className="text-sm text-gray-300 leading-relaxed">
          Describe the result. The agent chooses the character, workflow, endpoint, and settings.
        </p>
        <div className="rounded-xl border border-gray-800 bg-black/35 p-3">
          <p className="text-xs text-gray-300 leading-relaxed">“Generate an image of me walking through a rainy cyberpunk street.”</p>
        </div>
      </section>

      <div className="grid grid-cols-3 gap-2">
        {[
          ["image", "Image"],
          ["t2v", "Text → Video"],
          ["i2v", "Image → Video"],
        ].map(([id, label]) => (
          <button
            key={id}
            onClick={() => selectMode(id as GenerateMode)}
            className={`rounded-lg border px-2 py-2 text-xs font-medium transition ${
              mode === id
                ? "border-rose-500/60 bg-rose-600/15 text-rose-200"
                : "border-gray-800 bg-gray-950/60 text-gray-500 hover:text-gray-300"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <label className="block space-y-2">
        <span className="text-xs font-medium text-gray-400">Character</span>
        <select
          value={characterId}
          onChange={(event) => setCharacterId(event.target.value)}
          className="w-full rounded-lg bg-gray-950 border border-gray-800 px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-600"
        >
          <option value="none">No character / raw workflow</option>
          {characters.map((character) => (
            <option key={character.id} value={character.id}>
              {character.name}{character.trigger ? ` · trigger: ${character.trigger}` : ""}
            </option>
          ))}
        </select>
        {selectedCharacter && (
          <p className="text-[10px] text-gray-600 leading-relaxed">
            Uses this character’s LoRA when available. Trigger word <span className="text-gray-400">{selectedCharacter.trigger || "none"}</span> is added automatically if it is missing from your prompt.
          </p>
        )}
      </label>

      <label className="block space-y-2">
        <span className="text-xs font-medium text-gray-400">Prompt / idea</span>
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          rows={8}
          className="w-full rounded-lg bg-gray-950 border border-gray-800 px-3 py-2 text-sm text-white leading-relaxed resize-y focus:outline-none focus:border-rose-600"
        />
      </label>

      {mode === "image" && characterId === "none" && (
        <label className="block space-y-2">
          <span className="text-xs font-medium text-gray-400">Raw image checkpoint</span>
          <select
            value={checkpoint}
            onChange={(event) => setCheckpoint(event.target.value)}
            className="w-full rounded-lg bg-gray-950 border border-gray-800 px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-600"
          >
            <option value="base">Base Flux2 model — no LoRA</option>
            <option value="latest">Latest available LoRA checkpoint</option>
            {checkpoints.map((item) => (
              <option key={item.name} value={item.name}>
                {checkpointLabel(item)}
              </option>
            ))}
          </select>
          <p className="text-[10px] text-gray-600 leading-relaxed">
            Raw image mode bypasses character selection. Use base Flux2 or optionally apply a LoRA checkpoint directly.
          </p>
        </label>
      )}

      {mode === "image" && characterId !== "none" && selectedCharacter && !selectedCharacterHasImageLora && (
        <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-xs text-amber-200">
          This character does not have an image LoRA registered for the current workflow yet.
        </div>
      )}

      {mode === "i2v" && (
        <label className="block space-y-2">
          <span className="text-xs font-medium text-gray-400">Source image from gallery</span>
          <input
            value={sourceImage}
            onChange={(event) => setSourceImage(event.target.value)}
            placeholder="images/example.png"
            className="w-full rounded-lg bg-gray-950 border border-gray-800 px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-600"
          />
          <p className="text-[10px] text-gray-600">Open a gallery item and use its filename as the source.</p>
        </label>
      )}

      <div className="grid grid-cols-2 gap-3">
        <NumberField label="Width" value={width} onChange={setWidth} min={512} max={2048} step={64} />
        <NumberField label="Height" value={height} onChange={setHeight} min={512} max={2048} step={64} />
        {mode === "image" && <NumberField label="Steps" value={steps} onChange={setSteps} min={1} max={60} step={1} />}
        {mode === "image" && <NumberField label="Guidance" value={guidance} onChange={setGuidance} min={1} max={10} step={0.5} />}
      </div>

      {mode === "image" && (
        <NumberField
          label="LoRA strength"
          value={loraStrength}
          onChange={setLoraStrength}
          min={0}
          max={2}
          step={0.05}
        />
      )}

      <button
        onClick={submit}
        disabled={submitting}
        className="w-full rounded-lg bg-rose-600 hover:bg-rose-500 disabled:bg-gray-800 disabled:text-gray-500 px-4 py-2.5 text-sm font-semibold transition"
      >
        {submitting ? "Queueing..." : mode === "image" ? "Generate image" : "Generate video"}
      </button>

      {error && (
        <div className="rounded-lg border border-red-900/60 bg-red-950/40 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {result && (
        <div className="rounded-lg border border-emerald-900/60 bg-emerald-950/30 p-3 space-y-2">
          <p className="text-sm font-medium text-emerald-200">Queued successfully</p>
          <div className="text-xs text-emerald-100/80 space-y-1 break-all">
            <p>Prompt ID: {result.prompt_id}</p>
            {result.checkpoint && <p>Checkpoint: {result.checkpoint}</p>}
            {result.lora_name && <p>LoRA: {result.lora_name}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-medium text-gray-400">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="w-full rounded-lg bg-gray-950 border border-gray-800 px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-600"
      />
    </label>
  );
}
