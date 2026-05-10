from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse, urlunparse

import httpx
import websockets

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .comfy import ComfyClient
from .config import ComfyNode, get_settings
from .db import close_db, delete_character, delete_media_rows, delete_project, delete_project_render_row, delete_project_scene, delete_project_shot, delete_project_shot_versions_by_files, get_character, get_job, get_latest_training_job, get_project, get_project_render, get_project_scene, get_project_shot, get_project_shot_version, get_project_shot_version_by_prompt, get_training_job, init_db, list_characters, list_datasets, list_jobs, list_media, list_project_renders, list_project_scenes, list_project_shot_versions, list_project_shots, list_projects, list_training_jobs, media_count, next_render_number, next_shot_version_number, save_job, save_training_job, update_job_metadata, update_job_status, update_training_job_status, upsert_character, upsert_dataset, upsert_media, upsert_project, upsert_project_render, upsert_project_scene, upsert_project_shot, upsert_project_shot_version, utc_from_timestamp
from .workflows import WAN_NEGATIVE, build_flux2_lora_image, build_wan22_i2v, build_wan22_t2v

# ── ElevenLabs TTS ──
# Default voice from the account's available voices. Users can override per-character or per-project.
ELEVENLABS_VOICE_ID = "CwhRBWXzGAHq8TQ4Fs17"  # Roger — Laid-Back, Casual, Resonant


async def _generate_tts(text: str, output_path: Path, voice_id: str | None = None, voice_settings: dict[str, Any] | None = None) -> tuple[bool, float | None]:
    """Generate TTS audio via ElevenLabs with-timestamps endpoint.

    Returns (success, speech_end_seconds) where speech_end_seconds is the exact
    moment the last character is spoken, or None if unavailable.
    """
    settings = get_settings()
    api_key = settings.elevenlabs_api_key
    if not api_key:
        return False, None
    payload: dict[str, Any] = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
    }
    vs = voice_settings or {}
    payload["voice_settings"] = {
        "stability": vs.get("stability", 0.6),
        "similarity_boost": vs.get("similarity_boost", 0.8),
        "style": vs.get("style", 0.2),
        "use_speaker_boost": vs.get("use_speaker_boost", True),
    }
    import base64
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id or ELEVENLABS_VOICE_ID}/with-timestamps",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        audio_bytes = base64.b64decode(data["audio_base64"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        alignment = data["alignment"]
        end_times = alignment["character_end_times_seconds"]
        speech_end = float(end_times[-1])
        return True, speech_end


async def _tts_voices() -> list[dict[str, Any]]:
    """List available ElevenLabs voices."""
    settings = get_settings()
    api_key = settings.elevenlabs_api_key
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {
                    "voice_id": v.get("voice_id"),
                    "name": v.get("name"),
                    "category": v.get("category"),
                    "labels": v.get("labels", {}),
                    "description": v.get("description"),
                }
                for v in data.get("voices", [])
            ]
    except Exception:
        return []


app = FastAPI(
    title="Nemoflix AMD API",
    description="Agent-native API for driving ComfyUI video generation on AMD GPUs.",
    version="0.1.0",
)


class CharacterBinding(BaseModel):
    id: str = Field(min_length=1)
    role: str | None = None
    reference_image: str | None = None
    lora_strength: float | None = None


class CharacterLoraBinding(BaseModel):
    workflow: str
    name: str
    strength: float = 1.0
    base_model: str | None = None


class VoiceConfig(BaseModel):
    """TTS voice configuration for a character or narrator."""
    provider: str = "elevenlabs"
    voice_id: str
    name: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class CharacterRecord(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1)
    kind: Literal["human", "agent"] | None = None
    trigger: str | None = None
    description: str | None = None
    source_images: list[str] = Field(default_factory=list)
    loras: list[CharacterLoraBinding] = Field(default_factory=list)
    voice: VoiceConfig | None = None
    defaults: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectRecord(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    aspect_ratio: str = "9:16"
    duration_seconds: int | None = None
    status: str = "draft"
    characters: list[str] = Field(default_factory=list)
    narrator_voice: VoiceConfig | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneRecord(BaseModel):
    id: str | None = None
    project_id: str | None = None
    scene_number: int = Field(ge=1)
    title: str | None = None
    setting: str = "interior"
    weather: str = "clear"
    summary: str | None = None
    location: str | None = None
    time_of_day: str | None = None
    characters: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShotVersionRecord(BaseModel):
    id: str | None = None
    project_id: str | None = None
    scene_id: str | None = None
    shot_id: str | None = None
    version_number: int | None = None
    kind: Literal["image", "video"]
    status: str = "pending"
    prompt: str | None = None
    file: str | None = None
    prompt_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShotRecord(BaseModel):
    id: str | None = None
    project_id: str | None = None
    scene_id: str | None = None
    shot_number: int = Field(ge=1)
    text: str | None = None
    description: str | None = None
    subtitle: str | None = None
    speaker: str | None = None
    image_prompt: str | None = None
    motion_prompt: str | None = None
    characters: list[str] = Field(default_factory=list)
    duration_seconds: int = 5
    status: str = "draft"
    image_file: str | None = None
    video_file: str | None = None
    image_prompt_id: str | None = None
    video_prompt_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VideoGenerateRequest(BaseModel):
    mode: Literal["t2v", "i2v"] = "i2v"
    prompt: str = Field(min_length=1)
    character: str | None = Field(default=None, description="Shortcut for one character binding")
    characters: list[CharacterBinding] = Field(default_factory=list)
    image: str | None = Field(default=None, description="ComfyUI input filename for image-to-video")
    negative: str = WAN_NEGATIVE
    width: int = 640
    height: int = 640
    length: int = Field(default=81, description="Frame count, not seconds")
    fps: int = 16
    seed: int | None = None
    filename_prefix: str | None = None
    steps_high: int = 2
    steps_low: int = 2
    cfg_high: float = 1.0
    cfg_low: float = 1.0
    shift: float = 5.0
    sampler: str = "euler"
    scheduler: str = "simple"

    # I2V model overrides. Defaults target the official Comfy-Org Wan 2.2 I2V fp8 stack.
    high_model: str = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
    low_model: str = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
    vae: str = "wan_2.1_vae.safetensors"
    clip: str = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    high_lora: str | None = None
    low_lora: str | None = None
    high_lora_strength: float = 1.0
    low_lora_strength: float = 1.0

    submit: bool = Field(default=True, description="false returns workflow JSON without queueing")


class VideoGenerateResponse(BaseModel):
    ok: bool
    mode: str
    prompt_id: str | None = None
    number: int | None = None
    node_errors: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None


class ImageGenerateRequest(BaseModel):
    workflow: Literal["flux2_lora"] = "flux2_lora"
    character: str | None = Field(default=None, description="Shortcut for one character binding")
    characters: list[CharacterBinding] = Field(default_factory=list)
    checkpoint: str | None = Field(default=None, description="LoRA checkpoint filename, path under the LoRA output dir, or 'latest'")
    prompt: str = Field(min_length=1)
    width: int = 1248
    height: int = 832
    seed: int | None = None
    filename_prefix: str | None = None
    steps: int = 20
    cfg: float = 4.0
    sampler: str = "euler"
    guidance: float = 4.0
    unet: str = "flux2_dev_fp8mixed.safetensors"
    clip: str = "mistral_3_small_flux2_bf16.safetensors"
    vae: str = "flux2-vae.safetensors"
    lora_strength: float = 1.0
    submit: bool = Field(default=True, description="false returns workflow JSON without queueing")


class ImageGenerateResponse(BaseModel):
    ok: bool
    workflow: str
    checkpoint: str | None = None
    lora_name: str | None = None
    prompt_id: str | None = None
    number: int | None = None
    node_errors: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None


class JobOutput(BaseModel):
    type: str
    filename: str
    subfolder: str = ""
    folder_type: str = "output"
    url: str


class JobStatusResponse(BaseModel):
    ok: bool
    prompt_id: str
    status: str
    progress: float | None = None
    queue_position: int | None = None
    outputs_count: int | None = None
    outputs: list[JobOutput] = []
    raw: dict[str, Any] | None = None


class LoraTrainingStatus(BaseModel):
    ok: bool
    status: str
    job_name: str | None = None
    current_step: int = 0
    total_steps: int = 0
    progress_percent: float | None = None
    loss: float | None = None
    lr: float | None = None
    elapsed: str | None = None
    eta: str | None = None
    seconds_per_step: float | None = None
    gpu_util: float | None = None
    vram_percent: float | None = None
    info: str | None = None
    speed_string: str | None = None
    log_path: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    total_duration_seconds: float | None = None
    updated_at: str
    error: str | None = None


class LoraCheckpoint(BaseModel):
    name: str
    step: int | None = None
    path: str
    size_bytes: int
    modified_at: str


class LoraCheckpointsResponse(BaseModel):
    ok: bool
    job_name: str
    checkpoints: list[LoraCheckpoint]
    count: int
    updated_at: str


class LoraTrainingStartRequest(BaseModel):
    # -- Job ------------------------------------------------------------------
    job_name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    trigger_word: str = Field(min_length=1)
    base_config: Literal["flux2_identity", "wan22_i2v_character"] = "flux2_identity"
    dataset: str = Field(min_length=1, description="Dataset folder name on the droplet under /root/nemoflix-training/datasets/")

    # -- Model -----------------------------------------------------------------
    model: Literal["flux2_dev", "flux2_klein_4b", "flux2_klein_9b", "wan22_i2v_14b", "wan22_t2v_14b"] = "flux2_dev"
    model_name_or_path: str = Field(default="black-forest-labs/FLUX.2-dev", description="Hugging Face repo id for the base checkpoint")
    low_vram: bool = Field(default=False, description="Enable Low VRAM mode (Tier A 16-24 GB)")
    layer_offloading: bool = Field(default=False, description="Stream layers from CPU RAM (Tier A only)")
    transformer_quantization: Literal["qfloat8", "uint4", "none"] = Field(default="qfloat8")
    te_quantization: Literal["qfloat8", "uint4", "none"] = Field(default="qfloat8")

    # -- Target (LoRA network) -------------------------------------------------
    lora_rank: int = Field(default=32, ge=4, le=128)

    # -- Training --------------------------------------------------------------
    steps: int = Field(default=1800, ge=100, le=10000)
    learning_rate: float = Field(default=1e-4, ge=1e-6, le=1e-2)
    batch_size: int = Field(default=1, ge=1, le=8)
    gradient_accumulation: int = Field(default=1, ge=1, le=16)
    optimizer: Literal["adamw8bit", "adamw", "sgd"] = Field(default="adamw8bit")
    weight_decay: float = Field(default=1e-4, ge=0, le=1e-1)
    timestep_type: Literal["weighted", "sigmoid"] = Field(default="weighted")
    loss_type: Literal["mse", "l1", "huber"] = Field(default="mse")
    cache_text_embeddings: bool | None = Field(default=None, description="Auto: true unless DOP enabled. Encode captions once to save VRAM; incompatible with DOP or caption dropout.")
    unload_text_encoder: bool = Field(default=False, description="Unload TE after caching embeddings (VRAM saver)")

    # -- Dataset ---------------------------------------------------------------
    resolution: list[int] = Field(default=[768, 896, 1024], description="Resolution buckets for training")
    caption_dropout_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="Dropout rate for captions; set 0 when cache_text_embeddings is on")
    cache_latents: bool = Field(default=True, description="Cache VAE latents to disk to save VRAM")

    # -- Regularization --------------------------------------------------------
    dop_enabled: bool = Field(default=False, description="Differential Output Preservation — keep base model behaviour outside your trigger")
    preservation_class: str = Field(default="photo", description="Neutral class word for DOP non-trigger path")

    # -- Advanced --------------------------------------------------------------
    differential_guidance: bool = Field(default=False, description="Exaggerate the gap toward target for faster detail lock-in")
    differential_guidance_scale: float = Field(default=3.0, ge=1.0, le=10.0)

    # -- Sampling --------------------------------------------------------------
    sample_every: int = Field(default=250, ge=50, le=5000)
    sample_steps: int = Field(default=25, ge=10, le=100)
    sample_width: int = Field(default=1024, ge=512, le=2048)
    sample_height: int = Field(default=1024, ge=512, le=2048)
    sample_guidance_scale: float = Field(default=1.0, ge=0.0, le=10.0)
    sample_seed: int = Field(default=42)
    sample_prompts: list[str] = Field(default_factory=lambda: [
        "a person sitting at a cafe, holding a coffee cup, morning light through the window",
        "a person walking down a busy city street, candid shot, afternoon sun",
        "a person in a garden, surrounded by flowers, soft natural light, portrait",
    ])


class LoraTrainingStartResponse(BaseModel):
    ok: bool
    job_name: str
    status: str
    config_path: str
    output_dir: str
    error: str | None = None


def comfy(node: ComfyNode | None = None) -> ComfyClient:
    settings = get_settings()
    target = node or settings.comfy_node_for_role("default")
    return ComfyClient(target.comfyui.normalized_url, settings.request_timeout_seconds)


def comfy_for_role(role: str) -> tuple[ComfyClient, ComfyNode]:
    settings = get_settings()
    node = settings.comfy_node_for_role(role)  # type: ignore[arg-type]
    return ComfyClient(node.comfyui.normalized_url, settings.request_timeout_seconds), node


_WS_TASK: asyncio.Task | None = None
_SSE_CLIENTS: set[asyncio.Queue] = set()


async def _sse_broadcast(event: str, data: dict[str, Any]) -> None:
    if not _SSE_CLIENTS:
        return
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead = set()
    for q in _SSE_CLIENTS:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.add(q)
    _SSE_CLIENTS.difference_update(dead)


def _ws_url(base_url: str, client_id: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/ws", "", f"clientId={client_id}", ""))


def _progress_state_metadata(nodes: dict[str, Any]) -> dict[str, Any]:
    total = len(nodes)
    finished = 0
    running = 0
    current_node = None
    step_value = 0
    step_max = 0
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        state = node.get("state")
        if state == "finished":
            finished += 1
        elif state == "running":
            running += 1
            if current_node is None:
                current_node = node.get("display_node_id") or node.get("node_id") or node_id
                step_value = int(node.get("value") or 0)
                step_max = int(node.get("max") or 0)
    percent = round((finished / total) * 100, 1) if total else None
    return {
        "nodes_total": total,
        "nodes_finished": finished,
        "nodes_running": running,
        "current_node": current_node,
        "step_value": step_value,
        "step_max": step_max,
        "progress_percent": percent,
    }


async def _comfy_ws_bridge() -> None:
    settings = get_settings()
    node = settings.comfy_node_for_role("default")
    url = _ws_url(node.comfyui.normalized_url, node.comfy_client_id)
    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    msg_type = msg.get("type")
                    data = msg.get("data", {}) if isinstance(msg.get("data"), dict) else {}
                    prompt_id = data.get("prompt_id") or data.get("prompt")
                    if msg_type == "execution_start" and isinstance(prompt_id, str):
                        await update_job_status(prompt_id, "running")
                        await _sse_broadcast("job_update", {"prompt_id": prompt_id, "status": "running"})
                    elif msg_type == "progress_state" and isinstance(prompt_id, str):
                        nodes = data.get("nodes", {})
                        if isinstance(nodes, dict):
                            await update_job_metadata(prompt_id, _progress_state_metadata(nodes))
                    elif msg_type == "progress" and isinstance(prompt_id, str):
                        value = int(data.get("value") or 0)
                        max_value = int(data.get("max") or 0)
                        pct = round((value / max_value) * 100, 1) if max_value else None
                        await update_job_metadata(prompt_id, {
                            "step_value": value,
                            "step_max": max_value,
                            "progress_percent": pct,
                        })
                        await _sse_broadcast("job_update", {"prompt_id": prompt_id, "status": "running", "progress_percent": pct})
                    elif msg_type == "execution_success" and isinstance(prompt_id, str):
                        await update_job_metadata(prompt_id, {"progress_percent": 100})
                        try:
                            history = await comfy().get(f"/history/{prompt_id}")
                            outputs = _extract_outputs(history, comfy())
                            await _persist_outputs(prompt_id, outputs)
                        except Exception:
                            pass
                        await _sse_broadcast("job_update", {"prompt_id": prompt_id, "status": "completed"})
                    elif msg_type in {"execution_error", "execution_interrupted"} and isinstance(prompt_id, str):
                        error = data.get("exception_message") or msg_type
                        await update_job_status(prompt_id, "failed", error=error)
                        await _sse_broadcast("job_update", {"prompt_id": prompt_id, "status": "failed", "error": error})
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(3)


@app.get("/api/events")
async def sse_events(request: Request) -> StreamingResponse:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
    _SSE_CLIENTS.add(q)

    async def stream():
        try:
            yield "data: {\"type\": \"connected\"}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _SSE_CLIENTS.discard(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@app.on_event("startup")
async def start_comfy_bridge() -> None:
    global _WS_TASK
    await init_db()
    await _seed_builtin_characters()
    if _WS_TASK is None or _WS_TASK.done():
        _WS_TASK = asyncio.create_task(_comfy_ws_bridge())


@app.on_event("shutdown")
async def stop_comfy_bridge() -> None:
    global _WS_TASK
    if _WS_TASK:
        _WS_TASK.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _WS_TASK
        _WS_TASK = None
    await close_db()


async def _seed_builtin_characters() -> None:
    existing = await get_character("rigo")
    if existing:
        return
    await upsert_character({
        "id": "rigo",
        "name": "Rodrigo (NemoFlix)",
        "kind": "human",
        "trigger": "Rigo",
        "source_images": ["images/rigo-lora-api-test_00001_.png"],
        "loras": [{
            "workflow": "flux2_lora",
            "name": "nemoflix-amd/rigo_flux2_lora_v1_dop.safetensors",
            "strength": 1.0,
            "base_model": "flux2",
        }],
        "defaults": {
            "image_workflow": "flux2_lora",
            "video_workflow": "wan22_i2v",
            "reference_image": "images/rigo-lora-api-test_00001_.png",
        },
        "metadata": {"seeded": True},
    })


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _record_with_id(data: BaseModel, prefix: str, **overrides: Any) -> dict[str, Any]:
    record = data.model_dump()
    record.update(overrides)
    if not record.get("id"):
        record["id"] = _new_id(prefix)
    return record


def _request_character_bindings(character: str | None, characters: list[CharacterBinding]) -> list[CharacterBinding]:
    bindings = list(characters)
    if character and not any(binding.id == character for binding in bindings):
        bindings.insert(0, CharacterBinding(id=character))
    return bindings


async def _resolve_characters(character: str | None, characters: list[CharacterBinding]) -> list[tuple[CharacterBinding, dict[str, Any]]]:
    resolved: list[tuple[CharacterBinding, dict[str, Any]]] = []
    for binding in _request_character_bindings(character, characters):
        record = await get_character(binding.id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Character not found: {binding.id}")
        resolved.append((binding, record))
    return resolved


def _prompt_with_character_triggers(prompt: str, records: list[dict[str, Any]]) -> str:
    triggers = [record.get("trigger") for record in records if record.get("trigger")]
    missing = [trigger for trigger in triggers if trigger.lower() not in prompt.lower()]
    if not missing:
        return prompt
    return f"{', '.join(missing)}, {prompt}"


def _character_loras(records: list[dict[str, Any]], workflow: str, bindings: list[CharacterBinding]) -> list[dict[str, Any]]:
    loras: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        binding_strength = bindings[index].lora_strength if index < len(bindings) else None
        for lora in record.get("loras") or []:
            if lora.get("workflow") != workflow:
                continue
            loras.append({
                "name": lora.get("name"),
                "strength": binding_strength if binding_strength is not None else float(lora.get("strength", 1.0)),
                "character_id": record.get("id"),
            })
    return loras


def _character_reference_image(binding: CharacterBinding, record: dict[str, Any]) -> str | None:
    if binding.reference_image and binding.reference_image != "latest_best":
        return binding.reference_image
    defaults = record.get("defaults") or {}
    if defaults.get("reference_image"):
        return defaults["reference_image"]
    images = record.get("source_images") or []
    return images[0] if images else None


async def _ensure_comfy_input_image(image: str) -> str:
    source = (_OUTPUT_DIR / image.lstrip("/")).resolve()
    if not str(source).startswith(str(_OUTPUT_DIR.resolve())) or not source.is_file():
        return image
    tmp_path = Path(tempfile.gettempdir()) / source.name
    shutil.copy2(source, tmp_path)
    try:
        result = await comfy().upload_image(tmp_path)
        return result.get("name") or image
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/agent/chat")
async def agent_chat(payload: dict[str, Any]) -> dict[str, Any]:
    """Demo in-app agent endpoint for assistant-ui. Tool execution will be layered here."""
    messages = payload.get("messages") or []

    def _text_from_part(part: Any) -> str:
        if isinstance(part, str):
            return part
        if not isinstance(part, dict):
            return ""
        if isinstance(part.get("text"), str):
            return part["text"]
        if isinstance(part.get("content"), str):
            return part["content"]
        return ""

    last_text = ""
    for message in reversed(messages if isinstance(messages, list) else []):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        parts = message.get("content") or message.get("parts") or []
        if isinstance(parts, str):
            last_text = parts
        elif isinstance(parts, list):
            last_text = " ".join(filter(None, (_text_from_part(part) for part in parts)))
        break

    text = (
        "I'm the built-in Nemoflix agent surface. I can use the same API shape OpenClaw uses: "
        "characters, image/video generation, projects, GPU nodes, and ai-toolkit LoRA training. "
        "For this hackathon demo I'm wired through assistant-ui; the next step is enabling tool execution for requests like"
        f" ‘{last_text or 'generate an image'}'."
    )
    return {"ok": True, "text": text}


@app.get("/api/characters")
async def characters() -> dict[str, Any]:
    items = await list_characters()
    return {"characters": items, "count": len(items)}


@app.get("/api/characters/{character_id}")
async def character_detail(character_id: str) -> dict[str, Any]:
    record = await get_character(character_id)
    if not record:
        raise HTTPException(status_code=404, detail="Character not found")
    return record


@app.post("/api/characters", response_model=CharacterRecord)
async def create_character(character: CharacterRecord) -> CharacterRecord:
    record = await upsert_character(character.model_dump())
    return CharacterRecord(**record)


@app.patch("/api/characters/{character_id}", response_model=CharacterRecord)
async def patch_character(character_id: str, patch: dict[str, Any]) -> CharacterRecord:
    current = await get_character(character_id)
    if not current:
        raise HTTPException(status_code=404, detail="Character not found")
    allowed = {"name", "kind", "trigger", "description", "source_images", "loras", "voice", "defaults", "metadata"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported character fields: {', '.join(unknown)}")
    current.update(patch)
    current["id"] = character_id
    record = await upsert_character(current)
    return CharacterRecord(**record)


@app.delete("/api/characters/{character_id}")
async def remove_character(character_id: str) -> dict[str, Any]:
    deleted = await delete_character(character_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Character not found")
    return {"ok": True, "id": character_id}


@app.get("/api/projects")
async def projects(limit: int = 100) -> dict[str, Any]:
    items = await list_projects(limit)
    # Augment each project with render count from the renders table
    for item in items:
        item["render_count"] = len(await list_project_renders(item["id"]))
    return {"projects": items, "count": len(items)}


@app.post("/api/projects", response_model=ProjectRecord)
async def create_project(project: ProjectRecord) -> ProjectRecord:
    record = _record_with_id(project, "prj")
    saved = await upsert_project(record)
    return ProjectRecord(**saved)


@app.get("/api/projects/{project_id}")
async def project_detail(project_id: str) -> dict[str, Any]:
    project = await get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    scenes = await list_project_scenes(project_id)
    shots = await list_project_shots(project_id)
    return {"project": project, "scenes": scenes, "shots": shots}


@app.patch("/api/projects/{project_id}", response_model=ProjectRecord)
async def patch_project(project_id: str, patch: dict[str, Any]) -> ProjectRecord:
    current = await get_project(project_id)
    if not current:
        raise HTTPException(status_code=404, detail="Project not found")
    allowed = {"title", "description", "aspect_ratio", "duration_seconds", "status", "characters", "narrator_voice", "metadata"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported project fields: {', '.join(unknown)}")
    current.update(patch)
    saved = await upsert_project(current)
    return ProjectRecord(**saved)


@app.delete("/api/projects/{project_id}")
async def remove_project(project_id: str) -> dict[str, Any]:
    deleted = await delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"ok": True, "id": project_id}


@app.get("/api/projects/{project_id}/scenes")
async def project_scenes(project_id: str) -> dict[str, Any]:
    if not await get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    scenes = await list_project_scenes(project_id)
    return {"scenes": scenes, "count": len(scenes)}


@app.post("/api/projects/{project_id}/scenes", response_model=SceneRecord)
async def create_project_scene(project_id: str, scene: SceneRecord) -> SceneRecord:
    if not await get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    record = _record_with_id(scene, "scn", project_id=project_id)
    saved = await upsert_project_scene(record)
    return SceneRecord(**saved)


@app.patch("/api/projects/{project_id}/scenes/{scene_id}", response_model=SceneRecord)
async def patch_project_scene(project_id: str, scene_id: str, patch: dict[str, Any]) -> SceneRecord:
    current = await get_project_scene(project_id, scene_id)
    if not current:
        raise HTTPException(status_code=404, detail="Scene not found")
    allowed = {"scene_number", "title", "setting", "weather", "summary", "location", "time_of_day", "characters", "metadata"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported scene fields: {', '.join(unknown)}")
    current.update(patch)
    saved = await upsert_project_scene(current)
    return SceneRecord(**saved)


@app.delete("/api/projects/{project_id}/scenes/{scene_id}")
async def remove_project_scene(project_id: str, scene_id: str) -> dict[str, Any]:
    deleted = await delete_project_scene(project_id, scene_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Scene not found")
    return {"ok": True, "id": scene_id}


@app.get("/api/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/versions")
async def project_shot_versions(project_id: str, scene_id: str, shot_id: str) -> dict[str, Any]:
    if not await get_project_shot(project_id, scene_id, shot_id):
        raise HTTPException(status_code=404, detail="Shot not found")
    versions = await list_project_shot_versions(project_id, scene_id, shot_id)
    return {"versions": versions, "count": len(versions)}


@app.post("/api/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/versions/{version_id}/select", response_model=ShotRecord)
async def select_project_shot_version(project_id: str, scene_id: str, shot_id: str, version_id: str) -> ShotRecord:
    shot = await get_project_shot(project_id, scene_id, shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")
    version = await get_project_shot_version(project_id, scene_id, shot_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")
    if version.get("status") != "completed" or not version.get("file"):
        raise HTTPException(status_code=400, detail="Only completed versions with files can be selected")
    if version.get("kind") == "image":
        shot.update({"image_file": version["file"], "status": "image_ready", "video_file": None, "video_prompt_id": None})
    else:
        shot.update({"video_file": version["file"], "status": "video_ready"})
    saved = await upsert_project_shot(shot)
    return ShotRecord(**saved)


@app.get("/api/projects/{project_id}/scenes/{scene_id}/shots")
async def project_scene_shots(project_id: str, scene_id: str) -> dict[str, Any]:
    if not await get_project_scene(project_id, scene_id):
        raise HTTPException(status_code=404, detail="Scene not found")
    shots = await list_project_shots(project_id, scene_id)
    return {"shots": shots, "count": len(shots)}


@app.post("/api/projects/{project_id}/scenes/{scene_id}/shots", response_model=ShotRecord)
async def create_project_shot(project_id: str, scene_id: str, shot: ShotRecord) -> ShotRecord:
    if not await get_project_scene(project_id, scene_id):
        raise HTTPException(status_code=404, detail="Scene not found")
    record = _record_with_id(shot, "sht", project_id=project_id, scene_id=scene_id)
    saved = await upsert_project_shot(record)
    return ShotRecord(**saved)


@app.patch("/api/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}", response_model=ShotRecord)
async def patch_project_shot(project_id: str, scene_id: str, shot_id: str, patch: dict[str, Any]) -> ShotRecord:
    current = await get_project_shot(project_id, scene_id, shot_id)
    if not current:
        raise HTTPException(status_code=404, detail="Shot not found")
    allowed = {"shot_number", "text", "description", "subtitle", "speaker", "image_prompt", "motion_prompt", "characters", "duration_seconds", "status", "image_file", "video_file", "image_prompt_id", "video_prompt_id", "metadata"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported shot fields: {', '.join(unknown)}")
    current.update(patch)
    saved = await upsert_project_shot(current)
    return ShotRecord(**saved)


@app.delete("/api/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}")
async def remove_project_shot(project_id: str, scene_id: str, shot_id: str) -> dict[str, Any]:
    deleted = await delete_project_shot(project_id, scene_id, shot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Shot not found")
    return {"ok": True, "id": shot_id}


def _wan_resolution(aspect_ratio: str | None) -> tuple[int, int]:
    # Wan 2.2 I2V works best at 640x640 per official ComfyUI blueprint.
    # Override project aspect ratio to prevent distortion.
    return (640, 640)


def _character_bindings_from_ids(ids: list[str]) -> list[CharacterBinding]:
    return [CharacterBinding(id=item) for item in ids]


async def _project_character_ids(project_id: str, scene_id: str, shot: dict[str, Any]) -> list[str]:
    if shot.get("characters"):
        return shot["characters"]
    scene = await get_project_scene(project_id, scene_id)
    if scene and scene.get("characters"):
        return scene["characters"]
    project = await get_project(project_id)
    return project.get("characters", []) if project else []


@app.post("/api/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/generate-image", response_model=ImageGenerateResponse)
async def generate_project_shot_image(project_id: str, scene_id: str, shot_id: str) -> ImageGenerateResponse:
    shot = await get_project_shot(project_id, scene_id, shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")
    if shot.get("status") in {"rendering_image", "animating"}:
        raise HTTPException(status_code=409, detail="Shot is already rendering")
    prompt = shot.get("description") or shot.get("image_prompt") or shot.get("text")
    if not prompt:
        raise HTTPException(status_code=400, detail="Shot description, image_prompt, or text is required")

    character_ids = await _project_character_ids(project_id, scene_id, shot)
    resolved = await _resolve_characters(None, _character_bindings_from_ids(character_ids))
    bindings = [binding for binding, _ in resolved]
    records = [record for _, record in resolved]
    resolved_prompt = _prompt_with_character_triggers(prompt, records)
    loras = _character_loras(records, "flux2_lora", bindings)
    if not loras:
        raise HTTPException(status_code=400, detail="No character LoRA resolved for image rendering")

    version_number = await next_shot_version_number(shot_id, "image")
    version_id = _new_id("ver")
    graph = build_flux2_lora_image(
        prompt=resolved_prompt,
        loras=loras,
        filename_prefix=f"projects/{project_id}/scene-{shot.get('shot_number', 1):02d}-{shot_id}-image-v{version_number:02d}",
    )
    try:
        image_client, image_node = comfy_for_role("image")
        result = await image_client.queue_prompt(graph, client_id=image_node.comfy_client_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ComfyUI prompt submission failed: {exc}") from exc

    prompt_id = result.get("prompt_id")
    if prompt_id:
        await upsert_project_shot_version({
            "id": version_id,
            "project_id": project_id,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "version_number": version_number,
            "kind": "image",
            "status": "pending",
            "prompt": resolved_prompt,
            "prompt_id": prompt_id,
            "metadata": {"character_ids": character_ids, "resolved_loras": loras},
        })
        shot.update({"status": "rendering_image", "image_prompt_id": prompt_id})
        await upsert_project_shot(shot)
        await save_job(
            prompt_id=prompt_id,
            job_type="project_image",
            status="pending",
            prompt=resolved_prompt,
            width=1248,
            height=832,
            workflow_json=graph,
            metadata={"project_id": project_id, "scene_id": scene_id, "shot_id": shot_id, "version_id": version_id, "output_role": "image", "character_ids": character_ids, "resolved_loras": loras},
        )

    return ImageGenerateResponse(ok="prompt_id" in result, workflow="flux2_lora", lora_name=loras[0].get("name"), prompt_id=prompt_id, number=result.get("number"), node_errors=result.get("node_errors"))


@app.post("/api/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}/animate", response_model=VideoGenerateResponse)
async def animate_project_shot(project_id: str, scene_id: str, shot_id: str) -> VideoGenerateResponse:
    shot = await get_project_shot(project_id, scene_id, shot_id)
    if not shot:
        raise HTTPException(status_code=404, detail="Shot not found")
    if shot.get("status") in {"rendering_image", "animating"}:
        raise HTTPException(status_code=409, detail="Shot is already rendering")
    prompt = shot.get("motion_prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Shot motion_prompt is required")

    character_ids = await _project_character_ids(project_id, scene_id, shot)
    resolved = await _resolve_characters(None, _character_bindings_from_ids(character_ids))
    bindings = [binding for binding, _ in resolved]
    records = [record for _, record in resolved]

    image = shot.get("image_file")
    if not image and resolved:
        image = _character_reference_image(bindings[0], records[0])
    if not image:
        raise HTTPException(status_code=400, detail="Shot image_file or character reference image is required")
    comfy_image = await _ensure_comfy_input_image(image)

    project = await get_project(project_id)
    width, height = _wan_resolution(project.get("aspect_ratio") if project else None)

    # Wan I2V takes identity from the input image, not from a character LoRA or trigger word.
    # Trigger injection and character LoRAs apply to image generation only.
    version_number = await next_shot_version_number(shot_id, "video")
    version_id = _new_id("ver")
    workflow = build_wan22_i2v(
        image=comfy_image,
        prompt=prompt,
        width=width,
        height=height,
        length=max(1, int(shot.get("duration_seconds") or 5) * 16),
        fps=16,
        filename_prefix=f"projects/{project_id}/scene-{shot.get('shot_number', 1):02d}-{shot_id}-video-v{version_number:02d}",
    )
    try:
        video_client, video_node = comfy_for_role("video")
        result = await video_client.queue_prompt(workflow, client_id=video_node.comfy_client_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ComfyUI prompt submission failed: {exc}") from exc

    prompt_id = result.get("prompt_id")
    if prompt_id:
        await upsert_project_shot_version({
            "id": version_id,
            "project_id": project_id,
            "scene_id": scene_id,
            "shot_id": shot_id,
            "version_number": version_number,
            "kind": "video",
            "status": "pending",
            "prompt": prompt,
            "prompt_id": prompt_id,
            "metadata": {"source_image": image, "character_ids": character_ids},
        })
        shot.update({"status": "animating", "video_prompt_id": prompt_id})
        await upsert_project_shot(shot)
        await save_job(
            prompt_id=prompt_id,
            job_type="project_video",
            status="pending",
            prompt=prompt,
            width=width,
            height=height,
            workflow_json=workflow,
            metadata={"project_id": project_id, "scene_id": scene_id, "shot_id": shot_id, "version_id": version_id, "output_role": "video", "source_image": image, "character_ids": character_ids},
        )

    return VideoGenerateResponse(ok="prompt_id" in result, mode="i2v", prompt_id=prompt_id, number=result.get("number"), node_errors=result.get("node_errors"))


def _srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def _set_render_status(project_id: str, status: str, error: str | None = None, final_video: str | None = None, render_id: str | None = None) -> None:
    # Update legacy metadata for backward compat (frontend watches this)
    project = await get_project(project_id)
    if project:
        meta = dict(project.get("metadata") or {})
        meta["render_status"] = status
        if error is not None:
            meta["render_error"] = error
        if final_video is not None:
            meta["final_video"] = final_video
        project["metadata"] = meta
        await upsert_project(project)

    # Update the proper project_renders record if we have a render_id
    if render_id:
        await upsert_project_render({
            "id": render_id,
            "project_id": project_id,
            "render_number": 0,  # not used on update
            "status": status,
            "final_video": final_video,
            "error_message": error,
        })


async def _probe_duration(path: Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return 5.0


async def _run_render(project_id: str, shots: list[dict[str, Any]], render_id: str) -> None:
    # Create the render record in the database
    render_number = await next_render_number(project_id)
    await upsert_project_render({
        "id": render_id,
        "project_id": project_id,
        "render_number": render_number,
        "status": "running",
    })

    out_path = (_OUTPUT_DIR / f"projects/{project_id}/render-{render_id}.mp4").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    clip_pairs: list[tuple[Path, dict[str, Any]]] = []
    for shot in shots:
        video_file = shot.get("video_file")
        image_file = shot.get("image_file")
        if video_file:
            p = (_OUTPUT_DIR / video_file).resolve()
            if not p.is_file():
                await _set_render_status(project_id, "failed", f"Missing clip for shot {shot['id']}: {video_file}")
                return
            clip_pairs.append((p, shot))
        elif image_file:
            img_p = (_OUTPUT_DIR / image_file).resolve()
            if not img_p.is_file():
                continue  # skip shots with missing image
            duration = float(shot.get("duration_seconds") or 5)
            still_path = _OUTPUT_DIR / f"projects/{project_id}/render-{render_id}-still-{shot['id']}.mp4"
            still_cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(img_p),
                "-t", str(duration),
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                str(still_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *still_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                await _set_render_status(project_id, "failed", f"Failed to freeze image for shot {shot['id']}")
                return
            clip_pairs.append((still_path, shot))
        # no media — skip

    if not clip_pairs:
        await _set_render_status(project_id, "failed", "No renderable clips found")
        return

    # ── Burn subtitle text into each clip ──
    output_clips: list[Path] = []
    for idx, (clip_path, shot) in enumerate(clip_pairs, start=1):
        subtitle_text = (shot.get("subtitle") or "").strip()
        if subtitle_text:
            import textwrap
            wrapped = "\n".join(textwrap.wrap(subtitle_text, width=32))
            safe_text = (
                wrapped
                .replace("\\", "\\\\")
                .replace("'", "'")
                .replace(":", "\\:")
                .replace("%", "\\%")
                .replace("\n", "\\n")
            )
            drawtext = (
                f"drawtext=text='{safe_text}'"
                f":fontsize=26:fontcolor=white:borderw=2:bordercolor=black"
                f":x=(w-text_w)/2:y=h-line_h*{wrapped.count(chr(10))+1}-50"
            )
            sub_path = _OUTPUT_DIR / f"projects/{project_id}/render-{render_id}-shot{idx:02d}-sub.mp4"
            sub_cmd = [
                "ffmpeg", "-y",
                "-i", str(clip_path),
                "-vf", drawtext,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "copy",
                str(sub_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *sub_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                await _set_render_status(project_id, "failed", f"subtitle burn failed shot {idx}: {stderr.decode(errors='replace')[-400:]}")
                return
            output_clips.append(sub_path)
        else:
            output_clips.append(clip_path)

    # ── Concatenate clips ──
    concat_tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, prefix="nemo_concat_")
    try:
        for p in output_clips:
            concat_tmp.write(f"file '{p}'\n")
        concat_tmp.flush()
        concat_path = concat_tmp.name
    finally:
        concat_tmp.close()

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path, "-c:v", "copy", "-c:a", "copy", str(out_path)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    Path(concat_path).unlink(missing_ok=True)

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-800:]
        await _set_render_status(project_id, "failed", err)
        return

    stat = out_path.stat()
    rel = str(out_path.relative_to(_OUTPUT_DIR))
    await upsert_media({
        "filename": rel,
        "type": "video",
        "size": stat.st_size,
        "workflow_type": "project_render",
        "prompt": project_id,
    })
    await _set_render_status(project_id, "completed", final_video=rel, render_id=render_id)


@app.post("/api/projects/{project_id}/render")
async def render_project(project_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    project = await get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    scenes = await list_project_scenes(project_id)
    ordered_shots: list[dict[str, Any]] = []
    for scene in scenes:
        shots = await list_project_shots(project_id, scene["id"])
        ordered_shots.extend(shots)

    if not ordered_shots:
        raise HTTPException(status_code=400, detail="Project has no shots")

    renderable = [s for s in ordered_shots if s.get("video_file") or s.get("image_file")]
    if not renderable:
        raise HTTPException(status_code=400, detail="No shots have images or video to render")

    render_id = _new_id("rnd")
    meta = dict(project.get("metadata") or {})
    meta.update({"render_status": "rendering", "render_id": render_id, "render_error": None, "final_video": None})
    project["metadata"] = meta
    await upsert_project(project)

    background_tasks.add_task(_run_render, project_id, ordered_shots, render_id)
    return {"ok": True, "render_id": render_id, "shot_count": len(ordered_shots)}


@app.get("/api/tts/voices")
async def list_tts_voices() -> dict[str, Any]:
    """List available ElevenLabs voices for TTS."""
    voices = await _tts_voices()
    return {"voices": voices}


@app.get("/api/projects/{project_id}/render")
async def render_project_status(project_id: str) -> dict[str, Any]:
    project = await get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = project.get("metadata") or {}
    final_video = meta.get("final_video")
    renders = await list_project_renders(project_id)
    return {
        "status": meta.get("render_status", "none"),
        "render_id": meta.get("render_id"),
        "final_video": final_video,
        "final_video_url": f"/media/{final_video}" if final_video else None,
        "render_error": meta.get("render_error"),
        "renders": [
            {
                "id": r["id"],
                "render_number": r["render_number"],
                "final_video": r["final_video"],
                "final_video_url": f"/media/{r['final_video']}" if r["final_video"] else None,
                "created_at": r["created_at"],
                "status": r["status"],
                "error_message": r["error_message"],
            }
            for r in renders
        ],
    }


@app.delete("/api/projects/{project_id}/renders/{render_id}")
async def delete_project_render(project_id: str, render_id: str) -> dict[str, Any]:
    project = await get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    render = await get_project_render(project_id, render_id)
    if not render:
        raise HTTPException(status_code=404, detail="Render not found")
    # Delete the file if it exists
    if render.get("final_video"):
        target = _safe_output_path(render["final_video"])
        if target and target.is_file():
            target.unlink()
    await delete_project_render_row(render_id)
    return {"ok": True}


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    configured_nodes = settings.gpu_nodes()
    comfy_nodes = settings.comfy_nodes()
    online = 0
    for configured in comfy_nodes:
        with contextlib.suppress(Exception):
            await comfy(configured).get("/system_stats")
            online += 1
    return {
        "ok": True,
        "nodes_total": len(configured_nodes),
        "comfy_nodes_total": len(comfy_nodes),
        "comfy_nodes_online": online,
        "comfy_nodes_offline": len(comfy_nodes) - online,
    }




@app.get("/api/nodes")
async def nodes() -> dict[str, Any]:
    """Return configured GPU/ComfyUI node status for the Studio Nodes tab."""
    settings = get_settings()
    result: dict[str, Any] = {}
    for configured in settings.gpu_nodes():
        node: dict[str, Any] = {
            "id": configured.id,
            "label": configured.label,
            "roles": configured.roles,
            "online": False,
            "metadata": configured.metadata,
            "runtimes": {},
        }
        if configured.comfyui:
            client = comfy(configured)
            node["url"] = configured.comfyui.normalized_url
            node["client_id"] = configured.comfy_client_id
            node["runtimes"]["comfyui"] = {"url": configured.comfyui.normalized_url, "client_id": configured.comfy_client_id, "online": False}
            try:
                stats = await client.get("/system_stats")
                node["online"] = True
                node["runtimes"]["comfyui"]["online"] = True
                node["system"] = stats.get("system", {}) if isinstance(stats, dict) else {}
                devices = stats.get("devices", []) if isinstance(stats, dict) else []
                if devices:
                    dev = devices[0]
                    node.update({
                        "gpu_name": dev.get("name", "?"),
                        "vram_total": dev.get("vram_total", 0),
                        "vram_free": dev.get("vram_free", 0),
                        "torch_vram_total": dev.get("torch_vram_total", 0),
                        "torch_vram_free": dev.get("torch_vram_free", 0),
                    })
                with contextlib.suppress(Exception):
                    queue = await client.get("/queue")
                    node["queue_running"] = len(queue.get("queue_running", [])) if isinstance(queue, dict) else 0
                    node["queue_pending"] = len(queue.get("queue_pending", [])) if isinstance(queue, dict) else 0
            except Exception as exc:  # noqa: BLE001 - status endpoint should report offline, not fail the UI
                node["error"] = str(exc)
                node["runtimes"]["comfyui"]["error"] = str(exc)
        if configured.ai_toolkit:
            node["runtimes"]["ai_toolkit"] = configured.ai_toolkit.model_dump()
        result[configured.id] = node
    return {"nodes": result}


@app.get("/api/comfy/{path:path}")
async def comfy_get(path: str) -> Any:
    """Read-only passthrough for Comfy discovery endpoints: models, queue, object_info, history, etc."""
    allowed_roots = ("system_stats", "object_info", "models", "queue", "history", "prompt", "features", "view")
    if not path.startswith(allowed_roots):
        raise HTTPException(status_code=403, detail="Only read-only Comfy discovery/status paths are exposed here")
    return await comfy().get(f"/{path}")


@app.post("/api/images/upload")
async def upload_image(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "upload.png").suffix or ".png"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(await file.read())
    try:
        result = await comfy().upload_image(tmp_path)
        return {"ok": True, "comfy": result, "image": result.get("name")}
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/video/generate", response_model=VideoGenerateResponse)
async def generate_video(body: VideoGenerateRequest) -> VideoGenerateResponse:
    # Character resolution only supplies a fallback reference image for i2v.
    # Wan video takes identity from the image, so character triggers and character LoRAs
    # are not injected here — pass body.high_lora/body.low_lora explicitly to override.
    resolved = await _resolve_characters(body.character, body.characters)
    bindings = [binding for binding, _ in resolved]
    character_records = [record for _, record in resolved]
    prompt = body.prompt

    image = body.image
    if body.mode == "i2v" and not image and resolved:
        image = _character_reference_image(bindings[0], character_records[0])
    if image:
        image = await _ensure_comfy_input_image(image)

    high_lora = body.high_lora
    low_lora = body.low_lora
    high_lora_strength = body.high_lora_strength
    low_lora_strength = body.low_lora_strength
    filename_prefix = _resolve_filename_prefix(body.filename_prefix, "videos")

    if body.mode == "i2v":
        if not image:
            raise HTTPException(status_code=400, detail="image is required for i2v mode. Upload first with /api/images/upload or supply a character with a reference image.")
        workflow = build_wan22_i2v(
            image=image,
            prompt=prompt,
            negative=body.negative,
            width=body.width,
            height=body.height,
            length=body.length,
            fps=body.fps,
            seed=body.seed,
            filename_prefix=filename_prefix,
            steps_high=body.steps_high,
            steps_low=body.steps_low,
            cfg_high=body.cfg_high,
            cfg_low=body.cfg_low,
            shift=body.shift,
            sampler=body.sampler,
            scheduler=body.scheduler,
            high_model=body.high_model,
            low_model=body.low_model,
            vae=body.vae,
            clip=body.clip,
            high_lora=high_lora,
            low_lora=low_lora,
            high_lora_strength=high_lora_strength,
            low_lora_strength=low_lora_strength,
        )
    else:
        workflow = build_wan22_t2v(
            prompt=prompt,
            negative=body.negative,
            width=body.width,
            height=body.height,
            length=body.length,
            fps=body.fps,
            seed=body.seed,
            filename_prefix=filename_prefix,
            steps_high=body.steps_high,
            steps_low=body.steps_low,
            cfg_high=body.cfg_high,
            cfg_low=body.cfg_low,
            shift=body.shift,
            sampler=body.sampler,
            scheduler=body.scheduler,
        )

    if not body.submit:
        return VideoGenerateResponse(ok=True, mode=body.mode, workflow=workflow)

    try:
        video_client, video_node = comfy_for_role("video")
        result = await video_client.queue_prompt(workflow, client_id=video_node.comfy_client_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ComfyUI prompt submission failed: {exc}") from exc

    prompt_id = result.get("prompt_id")
    if prompt_id:
        await save_job(
            prompt_id=prompt_id,
            job_type=f"wan22_{body.mode}",
            status="pending",
            prompt=prompt,
            width=body.width,
            height=body.height,
            workflow_json=workflow,
            metadata={**body.model_dump(), "resolved_image": image, "character_ids": [record.get("id") for record in character_records]},
        )
    return VideoGenerateResponse(
        ok="prompt_id" in result,
        mode=body.mode,
        prompt_id=prompt_id,
        number=result.get("number"),
        node_errors=result.get("node_errors"),
    )


def _extract_outputs(history: dict[str, Any], client: ComfyClient) -> list[JobOutput]:
    outputs: list[JobOutput] = []
    records = history.values() if isinstance(history, dict) else []
    for record in records:
        node_outputs = record.get("outputs", {}) if isinstance(record, dict) else {}
        for node_output in node_outputs.values():
            if not isinstance(node_output, dict):
                continue
            for key, output_type in (("video", "video"), ("videos", "video"), ("gifs", "video"), ("images", "image")):
                for item in node_output.get(key, []) or []:
                    filename = item.get("filename")
                    if not filename:
                        continue
                    subfolder = item.get("subfolder", "")
                    folder_type = item.get("type", "output")
                    outputs.append(JobOutput(
                        type=output_type,
                        filename=filename,
                        subfolder=subfolder,
                        folder_type=folder_type,
                        url=client.view_url_sync(filename, subfolder=subfolder, folder_type=folder_type),
                    ))
    return outputs


def _extract_outputs_from_comfy_job(job: dict[str, Any], client: ComfyClient) -> list[JobOutput]:
    outputs = job.get("outputs", {}) if isinstance(job, dict) else {}
    if not isinstance(outputs, dict):
        return []
    return _extract_outputs({job.get("id", "job"): {"outputs": outputs}}, client)


def _relative_output_path(output: JobOutput) -> str:
    return f"{output.subfolder.strip('/')}/{output.filename}" if output.subfolder else output.filename


async def _download_output_if_missing(output: JobOutput) -> Path | None:
    rel = _relative_output_path(output)
    target = (_OUTPUT_DIR / rel).resolve()
    output_root = _OUTPUT_DIR.resolve()
    if not str(target).startswith(str(output_root)):
        return None
    if target.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with httpx.AsyncClient(timeout=get_settings().request_timeout_seconds) as client:
            async with client.stream("GET", output.url) as response:
                response.raise_for_status()
                tmp = target.with_suffix(target.suffix + ".tmp")
                with tmp.open("wb") as fh:
                    async for chunk in response.aiter_bytes():
                        fh.write(chunk)
                tmp.replace(target)
        return target
    except Exception:
        target.unlink(missing_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.unlink(missing_ok=True)
        return None


async def _persist_outputs(prompt_id: str, outputs: list[JobOutput]) -> None:
    first_filename: str | None = None
    job_meta = await get_job(prompt_id) or {}
    for output in outputs:
        rel = _relative_output_path(output)
        target = await _download_output_if_missing(output)
        if not target or not target.is_file():
            continue
        first_filename = first_filename or rel
        width, height = _read_dimensions(target)
        stat = target.stat()
        await upsert_media({
            "filename": rel,
            "type": output.type,
            "width": width,
            "height": height,
            "size": stat.st_size,
            "modified": utc_from_timestamp(stat.st_mtime),
            "prompt": job_meta.get("prompt"),
            "steps": job_meta.get("steps"),
            "guidance": job_meta.get("guidance"),
            "sampler": job_meta.get("sampler"),
            "model": job_meta.get("model"),
            "vae": job_meta.get("vae"),
            "text_encoder": job_meta.get("text_encoder"),
            "loras": job_meta.get("loras"),
            "workflow_type": job_meta.get("mode"),
            "prompt_id": prompt_id,
            "source_image": job_meta.get("source_image"),
        })
    if first_filename:
        await update_job_status(prompt_id, "completed", output_filename=first_filename)
        project_id = job_meta.get("project_id")
        scene_id = job_meta.get("scene_id")
        shot_id = job_meta.get("shot_id")
        output_role = job_meta.get("output_role")
        if project_id and scene_id and shot_id and output_role in {"image", "video"}:
            version_id = job_meta.get("version_id")
            if version_id:
                version = await get_project_shot_version(project_id, scene_id, shot_id, version_id)
                if version:
                    version.update({"status": "completed", "file": first_filename})
                    await upsert_project_shot_version(version)
            shot = await get_project_shot(project_id, scene_id, shot_id)
            if shot:
                if output_role == "image":
                    shot.update({"image_file": first_filename, "status": "image_ready", "video_file": None, "video_prompt_id": None})
                else:
                    shot.update({"video_file": first_filename, "status": "video_ready"})
                await upsert_project_shot(shot)


async def _queue_position(client: ComfyClient, prompt_id: str) -> int | None:
    queue = await client.get("/queue")
    pending = queue.get("queue_pending", []) if isinstance(queue, dict) else []
    for index, item in enumerate(pending, start=1):
        if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
            return index
    return None


@app.get("/api/jobs")
async def jobs(include_completed: bool = False) -> dict[str, Any]:
    """Return jobs submitted through this API from durable Postgres state.

    ComfyUI remains the execution engine. Its live queue is used only to refresh
    status/queue position for jobs already registered in Postgres; arbitrary
    Comfy queue entries are not surfaced.
    """
    db_jobs = await list_jobs(limit=100)
    client = comfy()

    running_ids: set[str] = set()
    pending_positions: dict[str, int] = {}
    queue_error: str | None = None

    try:
        queue = await client.get("/queue")
    except Exception as exc:  # noqa: BLE001
        queue_error = str(exc)
    else:
        for item in queue.get("queue_running", []) if isinstance(queue, dict) else []:
            if isinstance(item, list) and len(item) > 1 and isinstance(item[1], str):
                running_ids.add(item[1])

        for position, item in enumerate(queue.get("queue_pending", []) if isinstance(queue, dict) else [], start=1):
            if isinstance(item, list) and len(item) > 1 and isinstance(item[1], str):
                pending_positions[item[1]] = position

    job_values: list[dict[str, Any]] = []
    for job in db_jobs:
        prompt_id = job["prompt_id"]
        if job.get("status") not in {"completed", "failed"} and queue_error is None:
            if prompt_id in running_ids:
                job["status"] = "running"
                job["queue_position"] = None
                await update_job_status(prompt_id, "running")
            elif prompt_id in pending_positions:
                job["status"] = "pending"
                job["queue_position"] = pending_positions[prompt_id]
                await update_job_status(prompt_id, "pending")
            else:
                job["queue_position"] = None
                try:
                    history = await client.get(f"/history/{prompt_id}")
                    outputs = _extract_outputs(history, client)
                except Exception as exc:  # noqa: BLE001
                    job["error"] = f"Unable to read Comfy history: {exc}"
                    job["_missing_from_comfy"] = True
                else:
                    if outputs:
                        await _persist_outputs(prompt_id, outputs)
                        job["status"] = "completed"
                        job["output_filename"] = outputs[0].filename
                    else:
                        # Comfy is the source of truth. If a job is neither in
                        # /queue nor /history, do not invent a status for it.
                        job["_missing_from_comfy"] = True

        job_values.append(job)

    if not include_completed:
        job_values = [
            job
            for job in job_values
            if job.get("status") not in {"completed", "failed"} and not job.get("_missing_from_comfy")
        ]
    jobs_list = sorted(
        job_values,
        key=lambda j: (j.get("status") != "running", j.get("queue_position") or 0, str(j.get("created_at") or "")),
    )
    result = {"jobs": jobs_list, "count": len(jobs_list)}
    if queue_error:
        result["error"] = queue_error
    return result


@app.get("/api/jobs/{prompt_id}", response_model=JobStatusResponse)
async def job(prompt_id: str) -> JobStatusResponse:
    client = comfy()

    # ComfyUI's normalized jobs endpoint reports pending/in_progress/completed.
    # It is the right polling surface for UI status. Raw /history only exists after completion.
    try:
        comfy_job = await client.get(f"/api/jobs/{prompt_id}")
        outputs = _extract_outputs_from_comfy_job(comfy_job, client)
        status = comfy_job.get("status", "unknown")
        if status in {"pending", "running", "completed", "failed", "unknown"}:
            await update_job_status(prompt_id, status)
        if status == "completed" and outputs:
            await _persist_outputs(prompt_id, outputs)
        progress = 100.0 if status == "completed" else None
        position = await _queue_position(client, prompt_id) if status == "pending" else None
        return JobStatusResponse(
            ok=True,
            prompt_id=prompt_id,
            status=status,
            progress=progress,
            queue_position=position,
            outputs_count=comfy_job.get("outputs_count"),
            outputs=outputs,
            raw=comfy_job,
        )
    except Exception:
        # Older ComfyUI builds may not have /api/jobs/{id}; fall back to history.
        history = await client.get(f"/history/{prompt_id}")
        outputs = _extract_outputs(history, client)
        status = "completed" if outputs else ("running" if history == {} else "unknown")
        if outputs:
            await _persist_outputs(prompt_id, outputs)
        await update_job_status(prompt_id, status)
        progress = 100.0 if outputs else None
        return JobStatusResponse(ok=True, prompt_id=prompt_id, status=status, progress=progress, outputs=outputs, raw=history)


import os

import yaml

from fastapi.responses import FileResponse, Response  # StreamingResponse imported at top

_OUTPUT_DIR = Path(get_settings().output_dir)
_ALLOW_EXT = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".gif"}


def _resolve_filename_prefix(prefix: str | None, subfolder: str) -> str:
    """Return a unique filename prefix.

    If prefix is None, generate a random 8-char hex ID under subfolder.
    If prefix is provided, raise 409 if any file with that prefix already exists locally.
    """
    if prefix is None:
        return f"{subfolder}/{uuid.uuid4().hex[:8]}"
    safe = prefix.strip().lstrip("/")
    existing = list((_OUTPUT_DIR / safe).parent.glob(f"{(_OUTPUT_DIR / safe).name}*"))
    if existing:
        raise HTTPException(status_code=409, detail=f"Filename prefix '{safe}' already exists — choose a different name.")
    return safe
_TRAINING_DIR = Path(os.environ.get("NEMOFLIX_TRAINING_DIR", "/home/ubuntu/nemoflix/training"))
_TRAINING_CONFIG_DIR = _TRAINING_DIR / "config"
# Droplet paths — these live on the GPU worker, referenced by name only from the VPS.
_DROPLET_TRAINING_DIR = Path("/root/nemoflix-training")
_DROPLET_OUTPUT_DIR = _DROPLET_TRAINING_DIR / "output"
_DROPLET_LOGS_DIR = _DROPLET_TRAINING_DIR / "logs"
_DROPLET_DATASETS_DIR = _DROPLET_TRAINING_DIR / "datasets"
_AITK_API_URL = get_settings().aitk_api_url
_AITK_AUTH_TOKEN = os.environ.get("AITK_API_TOKEN", "")
_AITK_GPU_IDS = os.environ.get("AITK_GPU_IDS", "0")


def _aitk_headers() -> dict[str, str]:
    if _AITK_AUTH_TOKEN:
        return {"Authorization": f"Bearer {_AITK_AUTH_TOKEN}"}
    return {}


# Local VPS paths for LoRA checkpoints synced from the droplet.
_LORA_OUTPUT_DIR = Path(os.environ.get("NEMOFLIX_LORA_OUTPUT_DIR", _OUTPUT_DIR / "loras"))
_COMFY_LORA_DIR = Path(os.environ.get("NEMOFLIX_COMFY_LORA_DIR", "/home/ubuntu/nemoflix/ComfyUI/models/loras/nemoflix-amd"))
_TRAINING_SAMPLES_DIR = _OUTPUT_DIR / "samples"


async def _fetch_sample_from_droplet(droplet_path: str, vps_dest: Path) -> bool:
    """Download a single sample image from the droplet to the VPS."""
    if vps_dest.exists():
        return True  # already synced
    encoded = quote(droplet_path, safe="")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{_AITK_API_URL}/api/img/{encoded}",
                headers=_aitk_headers(),
            )
            if resp.status_code == 200:
                vps_dest.parent.mkdir(parents=True, exist_ok=True)
                vps_dest.write_bytes(resp.content)
                return True
    except Exception:
        pass
    return False


async def _sync_training_samples(job_name: str) -> list[str]:
    """Fetch sample paths from ai-toolkit and sync the images to the VPS.

    Returns the list of VPS-relative paths for successfully synced samples.
    """
    aitk_job = await _aitk_job_by_ref(job_name)
    if not aitk_job:
        db_job = await get_training_job(job_name)
        return (db_job.get("metadata") or {}).get("sample_paths", []) if db_job else []

    aitk_id = aitk_job["id"]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{_AITK_API_URL}/api/jobs/{aitk_id}/samples",
                headers=_aitk_headers(),
            )
            if resp.status_code != 200:
                return []
            droplet_paths = resp.json().get("samples", [])
    except Exception:
        return []

    vps_rel_paths: list[str] = []
    for dp in droplet_paths:
        filename = Path(dp).name
        vps_rel = f"samples/{job_name}/{filename}"
        vps_abs = _OUTPUT_DIR / vps_rel
        if await _fetch_sample_from_droplet(dp, vps_abs):
            vps_rel_paths.append(vps_rel)

    # Cache the VPS-relative paths in DB metadata
    if vps_rel_paths:
        await update_training_job_status(
            job_name, aitk_job.get("status", "running"),
            metadata={"sample_paths": vps_rel_paths},
        )
    return vps_rel_paths


async def _aitk_job_by_ref(job_name: str) -> dict[str, Any] | None:
    """Look up an ai-toolkit job by job_ref (our job_name)."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"{_AITK_API_URL}/api/jobs",
                params={"job_ref": job_name},
                headers=_aitk_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return None


_MODEL_MAP: dict[str, dict[str, str]] = {
    "flux2_dev": {"architecture": "flux2", "name_or_path": "black-forest-labs/FLUX.2-dev"},
    "flux2_klein_4b": {"architecture": "flux2_klein", "name_or_path": "black-forest-labs/FLUX.2-klein-base-4B"},
    "flux2_klein_9b": {"architecture": "flux2_klein", "name_or_path": "black-forest-labs/FLUX.2-klein-base-9B"},
    "wan22_i2v_14b": {"architecture": "wan22_i2v", "name_or_path": "Wan-AI/Wan2.2-I2V-14B"},
    "wan22_t2v_14b": {"architecture": "wan22_t2v", "name_or_path": "Wan-AI/Wan2.2-T2V-14B"},
}

_TEMPLATE_MAP: dict[str, str] = {
    "flux2_identity": "flux2_identity_template.yaml",
    "wan22_i2v_character": "wan22_i2v_character_template.yaml",
}


def _build_training_config(request: LoraTrainingStartRequest) -> tuple[Path, dict[str, Any]]:
    template_name = _TEMPLATE_MAP[request.base_config]
    template_path = _TRAINING_DIR / template_name
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail=f"Training template not found: {template_name}")

    config = yaml.safe_load(template_path.read_text())
    job_name = request.job_name
    trigger = request.trigger_word
    process = config["config"]["process"][0]

    # --- Job identity ---------------------------------------------------------
    config["config"]["name"] = job_name
    process["trigger_word"] = trigger
    process["training_folder"] = str(_DROPLET_OUTPUT_DIR)

    # --- Model ----------------------------------------------------------------
    model_sec = process["model"]
    model_sec["name_or_path"] = request.model_name_or_path
    model_sec["low_vram"] = request.low_vram
    model_sec.setdefault("model_kwargs", {})
    if request.layer_offloading:
        model_sec["model_kwargs"]["layer_offloading"] = True
    model_sec["quantize"] = request.transformer_quantization != "none"
    if request.transformer_quantization != "none":
        model_sec["qtype"] = request.transformer_quantization
    model_sec["quantize_te"] = request.te_quantization != "none"
    if request.te_quantization != "none":
        model_sec["qtype_te"] = request.te_quantization

    # --- Target (LoRA) --------------------------------------------------------
    process["network"]["linear"] = request.lora_rank
    process["network"]["linear_alpha"] = request.lora_rank

    # --- Training -------------------------------------------------------------
    train_sec = process["train"]
    train_sec["steps"] = request.steps
    train_sec["lr"] = request.learning_rate
    train_sec["batch_size"] = request.batch_size
    train_sec["gradient_accumulation_steps"] = request.gradient_accumulation
    train_sec["optimizer"] = request.optimizer
    train_sec.setdefault("optimizer_params", {})
    train_sec["optimizer_params"]["weight_decay"] = request.weight_decay
    train_sec["timestep_type"] = request.timestep_type
    # Auto cache_text_embeddings: True unless DOP enabled
    if request.cache_text_embeddings is None:
        train_sec["cache_text_embeddings"] = not request.dop_enabled
    else:
        train_sec["cache_text_embeddings"] = request.cache_text_embeddings
    train_sec["unload_text_encoder"] = request.unload_text_encoder

    # --- Dataset --------------------------------------------------------------
    datasets = process.get("datasets", [])
    if datasets:
        ds = datasets[0]
        # Dataset lives on the droplet — use droplet path
        ds["folder_path"] = str(_DROPLET_DATASETS_DIR / request.dataset)
        ds["resolution"] = request.resolution
        ds["caption_dropout_rate"] = request.caption_dropout_rate
        ds["cache_latents_to_disk"] = request.cache_latents

    # --- Regularization (DOP) -------------------------------------------------
    if request.dop_enabled:
        process["differential_output_preservation"] = {
            "enabled": True,
            "trigger_word": trigger,
            "preservation_class": request.preservation_class,
        }
    elif "differential_output_preservation" in process:
        del process["differential_output_preservation"]

    # --- Advanced -------------------------------------------------------------
    process.setdefault("advanced", {})
    process["advanced"]["differential_guidance"] = request.differential_guidance
    process["advanced"]["differential_guidance_scale"] = request.differential_guidance_scale

    # --- Logging (always enable UILogger for progress tracking) ---------------
    process["logging"] = {"use_ui_logger": True}

    # --- Sampling -------------------------------------------------------------
    sample_sec = process["sample"]
    sample_sec["sample_every"] = request.sample_every
    sample_sec["sample_steps"] = request.sample_steps
    sample_sec["width"] = request.sample_width
    sample_sec["height"] = request.sample_height
    sample_sec["guidance_scale"] = request.sample_guidance_scale
    sample_sec["seed"] = request.sample_seed
    sample_sec["prompts"] = request.sample_prompts

    # --- Write config ---------------------------------------------------------
    output_path = _TRAINING_CONFIG_DIR / f"{job_name}.yaml"
    _TRAINING_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))

    return output_path, config


def _safe_output_path(rel: str) -> Path | None:
    target = (_OUTPUT_DIR / rel).resolve()
    if not str(target).startswith(str(_OUTPUT_DIR.resolve())):
        return None
    return target


def _read_dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.lower() in {".mp4", ".webm", ".gif"}:
        return 1280, 720
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.width, im.height
    except Exception:
        return 0, 0


async def _sync_filesystem_media(limit: int | None = None) -> None:
    entries: list[Path] = []
    try:
        iterator = _OUTPUT_DIR.rglob("*")
        for entry in iterator:
            if entry.is_file() and entry.suffix.lower() in _ALLOW_EXT and ".thumbs" not in entry.parts and "samples" not in entry.parts and not entry.name.startswith("render-"):
                entries.append(entry)
    except (FileNotFoundError, PermissionError):
        return
    entries.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    for entry in entries[:limit]:
        rel = str(entry.relative_to(_OUTPUT_DIR))
        width, height = _read_dimensions(entry)
        stat = entry.stat()
        await upsert_media({
            "filename": rel,
            "type": "video" if entry.suffix.lower() in {".mp4", ".webm", ".gif"} else "image",
            "width": width,
            "height": height,
            "size": stat.st_size,
            "modified": utc_from_timestamp(stat.st_mtime),
        })


def _media_item(row: dict[str, Any]) -> dict[str, Any]:
    filename = row["filename"]
    return {
        "name": Path(filename).name,
        "filename": filename,
        "type": row.get("type", "image"),
        "width": row.get("width") or 0,
        "height": row.get("height") or 0,
        "mtime": row.get("modified").timestamp() if row.get("modified") else 0,
        "url": f"/media/{filename}",
        "thumb": f"/media/{filename}",
        "prompt": row.get("prompt"),
        "prompt_id": row.get("prompt_id"),
    }




@app.post("/api/lora-training/start", response_model=LoraTrainingStartResponse)
async def lora_training_start(body: LoraTrainingStartRequest) -> LoraTrainingStartResponse:
    """Build the training config locally, then enqueue and start via ai-toolkit UI API."""
    config_path, config_dict = _build_training_config(body)

    job_name = body.job_name
    output_dir = str(_DROPLET_OUTPUT_DIR / job_name)

    await save_training_job(
        job_name,
        status="pending",
        config_path=str(config_path),
        log_path="",
        output_dir=output_dir,
        dataset=body.dataset,
        trigger_word=body.trigger_word,
        model=body.model,
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Create job in ai-toolkit queue
            create_resp = await client.post(
                f"{_AITK_API_URL}/api/jobs",
                json={
                    "name": job_name,
                    "gpu_ids": _AITK_GPU_IDS,
                    "job_config": config_dict,
                    "job_ref": job_name,
                    "job_type": "train",
                },
                headers=_aitk_headers(),
            )
            if create_resp.status_code == 409:
                # Already exists — fetch it
                existing = await client.get(
                    f"{_AITK_API_URL}/api/jobs",
                    params={"job_ref": job_name},
                    headers=_aitk_headers(),
                )
                existing.raise_for_status()
                aitk_job = existing.json()
            else:
                create_resp.raise_for_status()
                aitk_job = create_resp.json()

            aitk_id = aitk_job["id"]

            # Start the job (sets it to "queued")
            start_resp = await client.get(
                f"{_AITK_API_URL}/api/jobs/{aitk_id}/start",
                headers=_aitk_headers(),
            )
            start_resp.raise_for_status()

            # Start the queue so the worker actually processes the job
            queue_resp = await client.get(
                f"{_AITK_API_URL}/api/queue/{_AITK_GPU_IDS}/start",
                headers=_aitk_headers(),
            )
            queue_resp.raise_for_status()

        await update_training_job_status(job_name, "running")
        return LoraTrainingStartResponse(
            ok=True,
            job_name=job_name,
            status="running",
            config_path=str(config_path),
            output_dir=output_dir,
        )
    except Exception as exc:
        await update_training_job_status(job_name, "failed", error=str(exc))
        return LoraTrainingStartResponse(
            ok=False,
            job_name=job_name,
            status="failed",
            config_path=str(config_path),
            output_dir=output_dir,
            error=str(exc),
        )


@app.get("/api/lora-training/status", response_model=LoraTrainingStatus)
async def lora_training_status(job_name: str | None = None) -> LoraTrainingStatus:
    updated_at = datetime.now(UTC).isoformat()

    # Resolve job_name from our DB if not provided
    if not job_name:
        db_job = await get_latest_training_job()
        job_name = db_job["job_name"] if db_job else None

    if not job_name:
        return LoraTrainingStatus(
            ok=False,
            status="no_job",
            job_name=None,
            updated_at=updated_at,
            error="No training job found",
        )

    db_job = await get_training_job(job_name) if job_name else await get_latest_training_job()
    db_status = db_job.get("status", "configured") if db_job else "configured"
    started_at = (db_job.get("created_at").isoformat() if db_job and db_job.get("created_at") else None)

    aitk_job = await _aitk_job_by_ref(job_name)
    if aitk_job:
        # Sync any new samples from the droplet to the VPS
        await _sync_training_samples(job_name)

        step = aitk_job.get("step") or 0
        # Derive total_steps from job_config
        try:
            jc = json.loads(aitk_job.get("job_config") or "{}")
            total = jc.get("config", {}).get("process", [{}])[0].get("train", {}).get("steps", 0)
        except Exception:
            total = 0
        progress = round((step / total) * 100, 1) if total and step else None

        # Parse ETA from speed_string (format: "Xs/it" or "Xit/s")
        eta: str | None = None
        speed_string = aitk_job.get("speed_string")
        seconds_per_step: float | None = None
        if speed_string and total and step:
            m = re.search(r"([\d.]+)\s*s/it", speed_string)
            if m:
                sps = float(m.group(1))
                seconds_per_step = sps
                remaining = int((total - step) * sps)
                h, rem = divmod(remaining, 3600)
                mi, s = divmod(rem, 60)
                eta = f"{h}:{mi:02d}:{s:02d}" if h else f"{mi}:{s:02d}"

        aitk_status = aitk_job.get("status", db_status)
        return LoraTrainingStatus(
            ok=True,
            status=aitk_status,
            job_name=job_name,
            current_step=step,
            total_steps=total,
            progress_percent=progress,
            info=aitk_job.get("info"),
            speed_string=speed_string,
            seconds_per_step=seconds_per_step,
            eta=eta,
            updated_at=updated_at,
            started_at=started_at,
        )

    return LoraTrainingStatus(
        ok=True,
        status=db_status,
        job_name=job_name,
        updated_at=updated_at,
        started_at=started_at,
    )


def _lora_checkpoint_path(checkpoint: str, output_dir: Path | None = None) -> Path:
    od = output_dir or _LORA_OUTPUT_DIR
    if checkpoint == "latest":
        candidates = sorted(
            od.glob("*.safetensors"),
            key=lambda path: path.stat().st_mtime,
        ) if od.is_dir() else []
        if not candidates:
            raise HTTPException(status_code=404, detail="No LoRA checkpoints found")
        return candidates[-1]

    path = Path(checkpoint)
    if not path.is_absolute():
        path = od / checkpoint
    try:
        resolved = path.resolve()
        output_root = od.resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid checkpoint path: {checkpoint}") from exc
    if not str(resolved).startswith(str(output_root)):
        raise HTTPException(status_code=400, detail="Checkpoint must be inside the LoRA output directory")
    if resolved.suffix != ".safetensors" or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return resolved


def _comfy_lora_name_for_checkpoint(path: Path) -> str:
    _COMFY_LORA_DIR.mkdir(parents=True, exist_ok=True)
    link_path = _COMFY_LORA_DIR / path.name
    if not link_path.exists():
        link_path.symlink_to(path)
    return f"nemoflix-amd/{path.name}"


@app.post("/api/image/generate", response_model=ImageGenerateResponse)
async def generate_image(body: ImageGenerateRequest) -> ImageGenerateResponse:
    if body.workflow != "flux2_lora":
        raise HTTPException(status_code=400, detail=f"Unsupported image workflow: {body.workflow}")

    resolved = await _resolve_characters(body.character, body.characters)
    bindings = [binding for binding, _ in resolved]
    character_records = [record for _, record in resolved]
    prompt = _prompt_with_character_triggers(body.prompt, character_records)
    loras = _character_loras(character_records, body.workflow, bindings)

    checkpoint_name: str | None = None
    checkpoint_lora_name: str | None = None
    if body.checkpoint:
        checkpoint_path = _lora_checkpoint_path(body.checkpoint)
        checkpoint_name = checkpoint_path.name
        checkpoint_lora_name = _comfy_lora_name_for_checkpoint(checkpoint_path)
        loras.insert(0, {"name": checkpoint_lora_name, "strength": body.lora_strength, "checkpoint": checkpoint_name})

    filename_prefix = _resolve_filename_prefix(body.filename_prefix, "images")

    graph = build_flux2_lora_image(
        prompt=prompt,
        loras=loras,
        width=body.width,
        height=body.height,
        seed=body.seed,
        filename_prefix=filename_prefix,
        steps=body.steps,
        cfg=body.cfg,
        sampler=body.sampler,
        guidance=body.guidance,
        unet=body.unet,
        clip=body.clip,
        vae=body.vae,
        lora_strength=body.lora_strength,
    )

    resolved_lora_name = checkpoint_lora_name or (loras[0].get("name") if loras else None)

    if not body.submit:
        return ImageGenerateResponse(ok=True, workflow=body.workflow, checkpoint=checkpoint_name, lora_name=resolved_lora_name, graph=graph)

    try:
        image_client, image_node = comfy_for_role("image")
        result = await image_client.queue_prompt(graph, client_id=image_node.comfy_client_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ComfyUI prompt submission failed: {exc}") from exc

    prompt_id = result.get("prompt_id")
    if prompt_id:
        await save_job(
            prompt_id=prompt_id,
            job_type="flux2_lora_image",
            status="pending",
            prompt=prompt,
            width=body.width,
            height=body.height,
            workflow_json=graph,
            metadata={**body.model_dump(), "checkpoint": checkpoint_name, "lora_name": checkpoint_lora_name, "resolved_prompt": prompt, "character_ids": [record.get("id") for record in character_records], "resolved_loras": loras},
        )

    return ImageGenerateResponse(
        ok="prompt_id" in result,
        workflow=body.workflow,
        checkpoint=checkpoint_name,
        lora_name=resolved_lora_name,
        prompt_id=prompt_id,
        number=result.get("number"),
        node_errors=result.get("node_errors"),
    )


@app.get("/api/lora-training/checkpoints", response_model=LoraCheckpointsResponse)
async def lora_training_checkpoints(job_name: str | None = None) -> LoraCheckpointsResponse:
    updated_at = datetime.now(UTC).isoformat()
    seen: set[str] = set()
    checkpoints: list[LoraCheckpoint] = []

    def _add(path: Path) -> None:
        if path.name in seen:
            return
        seen.add(path.name)
        stat = path.stat()
        step_match = re.search(r"_(\d{6,})\.safetensors$", path.name)
        checkpoints.append(LoraCheckpoint(
            name=path.name,
            step=int(step_match.group(1)) if step_match else None,
            path=str(path),
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        ))

    # 1. Local VPS checkpoints — always available, persisted across droplets.
    for d in _LORA_OUTPUT_DIR.parent.glob("*"):
        if not d.is_dir():
            continue
        lora_dir = d / "loras"
        if not lora_dir.is_dir():
            continue
        for p in sorted(lora_dir.glob("*.safetensors")):
            if job_name and not p.stem.startswith(job_name):
                continue
            _add(p)
    if _LORA_OUTPUT_DIR.is_dir():
        for p in sorted(_LORA_OUTPUT_DIR.glob("*.safetensors")):
            if job_name and not p.stem.startswith(job_name):
                continue
            _add(p)

    checkpoints.sort(key=lambda item: item.step if item.step is not None else -1, reverse=True)
    return LoraCheckpointsResponse(
        ok=True,
        job_name="all",
        checkpoints=checkpoints,
        count=len(checkpoints),
        updated_at=updated_at,
    )


@app.get("/api/lora-training/jobs")
async def lora_training_jobs():
    jobs = await list_training_jobs()
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/lora-training/datasets")
async def lora_training_datasets_list():
    datasets = await list_datasets()
    return {"datasets": datasets, "count": len(datasets)}


class CreateDatasetRequest(BaseModel):
    id: str = Field(min_length=1, description="Folder name on the droplet under /root/nemoflix-training/datasets/")
    name: str = Field(min_length=1)
    description: str | None = None
    image_count: int | None = None


@app.post("/api/lora-training/datasets")
async def lora_training_datasets_create(body: CreateDatasetRequest):
    dataset = await upsert_dataset(body.id, body.name, body.description, body.image_count)
    return {"ok": True, "dataset": dataset}


@app.get("/api/lora-training/samples")
async def lora_training_samples(job_name: str):
    """List sample images synced from training to the VPS."""
    db_job = await get_training_job(job_name)
    paths = (db_job.get("metadata") or {}).get("sample_paths", []) if db_job else []
    return {"ok": True, "samples": paths, "count": len(paths)}


@app.get("/api/lora-training/sample-image")
async def lora_training_sample_image(path: str):
    """Serve a training sample image from the VPS output directory."""
    target = _OUTPUT_DIR / path.lstrip("/")
    target = target.resolve()
    if not str(target).startswith(str(_OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)


@app.get("/api/listing")
async def listing(dir: str = "", offset: int = 0, limit: int = 60) -> dict[str, Any]:
    # Backfill the database from ComfyUI's output folder before reading. This keeps
    # old files visible while new generations become durable DB records.
    await _sync_filesystem_media(limit=500)
    rows = await list_media(limit=limit, offset=offset)
    if dir:
        prefix = dir.strip("/") + "/"
        rows = [row for row in rows if str(row.get("filename", "")).startswith(prefix)]

    # The database is metadata, not durable media storage. If a disposable GPU
    # worker was destroyed before outputs were copied back, stale rows can point
    # at files that no longer exist on the VPS. Do not return broken media tiles.
    available_rows = [
        row for row in rows
        if (target := _safe_output_path(str(row.get("filename", "")))) is not None and target.is_file()
    ]
    return {"images": [_media_item(row) for row in available_rows], "total": len(available_rows), "offset": offset, "limit": limit}


@app.get("/media/{path:path}")
async def media(path: str) -> FileResponse:
    target = _safe_output_path(path)
    if not target:
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    stat = target.stat()
    etag = f'W/"{stat.st_mtime_ns}-{stat.st_size}"'
    return FileResponse(
        target,
        headers={"Cache-Control": "private, max-age=604800, immutable", "ETag": etag},
    )


@app.post("/api/delete")
async def delete_media(body: dict[str, Any]) -> dict[str, Any]:
    files = body.get("files", [])
    if not isinstance(files, list):
        raise HTTPException(status_code=400, detail="files must be a list")

    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, str):
            failed.append({"file": str(item), "error": "invalid filename"})
            continue
        target = _safe_output_path(item)
        if not target:
            failed.append({"file": item, "error": "invalid path"})
            continue
        try:
            if target.is_file():
                target.unlink()
            deleted.append(item)
        except Exception as exc:  # noqa: BLE001
            failed.append({"file": item, "error": str(exc)})

    if deleted:
        await delete_media_rows(deleted)
        await delete_project_shot_versions_by_files(deleted)
    return {"ok": not failed, "deleted": deleted, "failed": failed}

