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
from urllib.parse import urlparse, urlunparse

import httpx
import websockets

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .comfy import ComfyClient
from .config import ComfyNode, get_settings
from .db import close_db, delete_character, delete_media_rows, delete_project, delete_project_scene, delete_project_shot, get_character, get_job, get_project, get_project_scene, get_project_shot, get_project_shot_version, get_project_shot_version_by_prompt, init_db, list_characters, list_jobs, list_media, list_project_scenes, list_project_shot_versions, list_project_shots, list_projects, media_count, next_shot_version_number, save_job, update_job_metadata, update_job_status, upsert_character, upsert_media, upsert_project, upsert_project_scene, upsert_project_shot, upsert_project_shot_version, utc_from_timestamp
from .workflows import WAN_NEGATIVE, build_flux2_lora_image, build_wan22_i2v, build_wan22_t2v

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


class CharacterRecord(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1)
    kind: Literal["human", "agent"] | None = None
    trigger: str | None = None
    description: str | None = None
    source_images: list[str] = Field(default_factory=list)
    loras: list[CharacterLoraBinding] = Field(default_factory=list)
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
    voiceover: str | None = None
    image_prompt: str | None = None
    motion_prompt: str | None = None
    camera_motion: str | None = None
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
    width: int = 1280
    height: int = 720
    length: int = Field(default=121, description="Frame count, not seconds")
    fps: int = 16
    seed: int | None = None
    filename_prefix: str = "videos"
    steps_high: int = 2
    steps_low: int = 2
    cfg_high: float = 3.5
    cfg_low: float = 3.5
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
    filename_prefix: str = "images/generated"
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
    job_name: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    trigger_word: str = Field(min_length=1)
    dataset: str = Field(min_length=1, description="Dataset folder name under training/datasets/")
    model: Literal["flux2_dev", "flux2_klein_4b", "flux2_klein_9b", "wan22_i2v_14b", "wan22_t2v_14b"] = "flux2_dev"
    steps: int = Field(default=1800, ge=100, le=10000)
    lora_rank: int = Field(default=32, ge=4, le=128)
    learning_rate: float = Field(default=1e-4, ge=1e-6, le=1e-2)
    resolution: int = Field(default=1024, ge=512, le=2048, description="Max resolution bucket")
    base_config: Literal["flux2_identity", "wan22_i2v_character"] = "flux2_identity"


class LoraTrainingStartResponse(BaseModel):
    ok: bool
    job_name: str
    status: str
    config_path: str
    log_path: str
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
                    elif msg_type == "progress_state" and isinstance(prompt_id, str):
                        nodes = data.get("nodes", {})
                        if isinstance(nodes, dict):
                            await update_job_metadata(prompt_id, _progress_state_metadata(nodes))
                    elif msg_type == "progress" and isinstance(prompt_id, str):
                        value = int(data.get("value") or 0)
                        max_value = int(data.get("max") or 0)
                        await update_job_metadata(prompt_id, {
                            "step_value": value,
                            "step_max": max_value,
                            "progress_percent": round((value / max_value) * 100, 1) if max_value else None,
                        })
                    elif msg_type == "execution_success" and isinstance(prompt_id, str):
                        await update_job_metadata(prompt_id, {"progress_percent": 100})
                        try:
                            history = await comfy().get(f"/history/{prompt_id}")
                            outputs = _extract_outputs(history, comfy())
                            await _persist_outputs(prompt_id, outputs)
                        except Exception:
                            pass
                    elif msg_type in {"execution_error", "execution_interrupted"} and isinstance(prompt_id, str):
                        error = data.get("exception_message") or msg_type
                        await update_job_status(prompt_id, "failed", error=error)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(3)


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
        "I’m the built-in Nemoflix agent surface. I can use the same API shape OpenClaw uses: "
        "characters, image/video generation, projects, GPU nodes, and ai-toolkit LoRA training. "
        "For this hackathon demo I’m wired through assistant-ui; the next step is enabling tool execution for requests like"
        f" ‘{last_text or 'generate an image'}’."
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
    allowed = {"name", "kind", "trigger", "description", "source_images", "loras", "defaults", "metadata"}
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
    allowed = {"title", "description", "aspect_ratio", "duration_seconds", "status", "characters", "metadata"}
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
    allowed = {"shot_number", "text", "description", "subtitle", "voiceover", "image_prompt", "motion_prompt", "camera_motion", "characters", "duration_seconds", "status", "image_file", "video_file", "image_prompt_id", "video_prompt_id", "metadata"}
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
    return {"9:16": (720, 1280), "1:1": (1024, 1024)}.get(aspect_ratio or "", (1280, 720))


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
    prompt = shot.get("motion_prompt") or shot.get("text") or shot.get("image_prompt")
    if not prompt:
        raise HTTPException(status_code=400, detail="Shot motion_prompt, text, or image_prompt is required")

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


async def _set_render_status(project_id: str, status: str, error: str | None = None, final_video: str | None = None) -> None:
    project = await get_project(project_id)
    if not project:
        return
    meta = dict(project.get("metadata") or {})
    meta["render_status"] = status
    if error is not None:
        meta["render_error"] = error
    if final_video is not None:
        meta["final_video"] = final_video
    project["metadata"] = meta
    await upsert_project(project)


async def _run_render(project_id: str, shots: list[dict[str, Any]], render_id: str) -> None:
    out_path = (_OUTPUT_DIR / f"projects/{project_id}/render-{render_id}.mp4").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    clip_pairs: list[tuple[Path, dict[str, Any]]] = []
    for shot in shots:
        p = (_OUTPUT_DIR / shot["video_file"]).resolve()
        if not p.is_file():
            await _set_render_status(project_id, "failed", f"Missing clip for shot {shot['id']}: {shot['video_file']}")
            return
        clip_pairs.append((p, shot))

    concat_tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, prefix="nemo_concat_")
    try:
        for p, _ in clip_pairs:
            concat_tmp.write(f"file '{p}'\n")
        concat_tmp.flush()
        concat_path = concat_tmp.name
    finally:
        concat_tmp.close()

    srt_path: str | None = None
    srt_entries: list[str] = []
    cumulative = 0.0
    for idx, (_, shot) in enumerate(clip_pairs, start=1):
        duration = float(shot.get("duration_seconds") or 5)
        subtitle = (shot.get("subtitle") or "").strip()
        if subtitle:
            srt_entries.append(
                f"{idx}\n{_srt_timestamp(cumulative)} --> {_srt_timestamp(cumulative + duration)}\n{subtitle}\n"
            )
        cumulative += duration

    if srt_entries:
        srt_tmp = tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False, prefix="nemo_srt_")
        try:
            srt_tmp.write("\n".join(srt_entries))
            srt_tmp.flush()
            srt_path = srt_tmp.name
        finally:
            srt_tmp.close()

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path]
    if srt_path:
        style = "FontSize=22,PrimaryColour=&Hffffff,OutlineColour=&H000000,Outline=2,Alignment=2"
        cmd += ["-vf", f"subtitles={srt_path}:force_style='{style}'", "-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    else:
        cmd += ["-c:v", "copy"]
    cmd += ["-an", str(out_path)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    Path(concat_path).unlink(missing_ok=True)
    if srt_path:
        Path(srt_path).unlink(missing_ok=True)

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
    await _set_render_status(project_id, "completed", final_video=rel)


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

    missing = [s["id"] for s in ordered_shots if not s.get("video_file")]
    if missing:
        raise HTTPException(status_code=400, detail=f"Shots missing video: {missing}")

    render_id = _new_id("rnd")
    meta = dict(project.get("metadata") or {})
    meta.update({"render_status": "rendering", "render_id": render_id, "render_error": None, "final_video": None})
    project["metadata"] = meta
    await upsert_project(project)

    background_tasks.add_task(_run_render, project_id, ordered_shots, render_id)
    return {"ok": True, "render_id": render_id, "shot_count": len(ordered_shots)}


@app.get("/api/projects/{project_id}/render")
async def render_project_status(project_id: str) -> dict[str, Any]:
    project = await get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    meta = project.get("metadata") or {}
    final_video = meta.get("final_video")
    return {
        "status": meta.get("render_status", "none"),
        "render_id": meta.get("render_id"),
        "final_video": final_video,
        "final_video_url": f"/media/{final_video}" if final_video else None,
        "render_error": meta.get("render_error"),
    }


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
            filename_prefix=body.filename_prefix,
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
            filename_prefix=body.filename_prefix,
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

from fastapi.responses import FileResponse

_OUTPUT_DIR = Path(get_settings().output_dir)
_ALLOW_EXT = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".gif"}
_LORA_TRAINING_LOG = Path(os.environ.get("NEMOFLIX_LORA_TRAINING_LOG", "/root/rigo-flux2-dop-train.log"))
_LORA_JOB_NAME = os.environ.get("NEMOFLIX_LORA_JOB_NAME", "rigo_flux2_lora_v1_dop")
_LORA_OUTPUT_DIR = Path(os.environ.get("NEMOFLIX_LORA_OUTPUT_DIR", f"/root/nemoflix-training/output/{_LORA_JOB_NAME}"))
_COMFY_LORA_DIR = Path(os.environ.get("NEMOFLIX_COMFY_LORA_DIR", "/root/ComfyUI/models/loras/nemoflix-amd"))
_TRAINING_RUNNER = Path(os.environ.get("NEMOFLIX_TRAINING_RUNNER", "/root/nemoflix-training/run-ai-toolkit.sh"))
_TRAINING_CONFIG_DIR = Path(os.environ.get("NEMOFLIX_TRAINING_CONFIG_DIR", "/root/nemoflix-training/config"))
_TRAINING_DIR = Path(os.environ.get("NEMOFLIX_TRAINING_DIR", "/root/nemoflix-training"))
_ACTIVE_JOB_PATH = Path(os.environ.get("NEMOFLIX_ACTIVE_JOB_PATH", "/tmp/nemoflix-active-training-job.json"))


def _active_job_state() -> dict[str, Any]:
    try:
        return json.loads(_ACTIVE_JOB_PATH.read_text()) if _ACTIVE_JOB_PATH.is_file() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_active_job(state: dict[str, Any]) -> None:
    _ACTIVE_JOB_PATH.write_text(json.dumps(state))


def _resolve_job_context(job_name: str | None = None) -> tuple[str, Path, Path]:
    if job_name:
        log_path = _TRAINING_DIR / "logs" / f"{job_name}.log"
        output_dir = _TRAINING_DIR / "output" / job_name
        return job_name, log_path, output_dir
    active = _active_job_state()
    if active:
        name = active.get("job_name", _LORA_JOB_NAME)
        log_path = Path(active.get("log_path", str(_LORA_TRAINING_LOG)))
        output_dir = Path(active.get("output_dir", str(_LORA_OUTPUT_DIR)))
        return name, log_path, output_dir
    return _LORA_JOB_NAME, _LORA_TRAINING_LOG, _LORA_OUTPUT_DIR


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
    model_info = _MODEL_MAP[request.model]
    dataset_path = _TRAINING_DIR / "datasets" / request.dataset

    if not dataset_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Dataset not found: {request.dataset}")

    job_name = request.job_name
    trigger = request.trigger_word

    config["config"]["name"] = job_name
    config["config"]["process"][0]["trigger_word"] = trigger
    config["config"]["process"][0]["training_folder"] = str(_TRAINING_DIR / "output")
    config["config"]["process"][0]["network"]["linear"] = request.lora_rank
    config["config"]["process"][0]["network"]["linear_alpha"] = request.lora_rank
    config["config"]["process"][0]["train"]["steps"] = request.steps
    config["config"]["process"][0]["train"]["lr"] = request.learning_rate
    config["config"]["process"][0]["model"]["name_or_path"] = model_info["name_or_path"]

    datasets = config["config"]["process"][0].get("datasets", [])
    if datasets:
        datasets[0]["folder_path"] = str(dataset_path)
        # Use the closest standard bucket
        buckets = [r for r in [512, 768, 896, 1024, 1280, 1536] if r <= request.resolution]
        chosen = buckets[-1] if buckets else 1024
        datasets[0]["resolution"] = [chosen]

    output_path = _TRAINING_CONFIG_DIR / f"{job_name}.yaml"
    _TRAINING_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.dump(config, default_flow_style=False))

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
            if entry.is_file() and entry.suffix.lower() in _ALLOW_EXT and ".thumbs" not in entry.parts:
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


def _parse_rocm_value(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _read_gpu_status() -> tuple[float | None, float | None]:
    try:
        result = subprocess.run(
            ["/opt/rocm/bin/rocm-smi", "--showuse", "--showmemuse"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return None, None

    output = result.stdout + result.stderr
    gpu_util = _parse_rocm_value(r"GPU use \(%\):\s*([0-9.]+)", output)
    vram_percent = _parse_rocm_value(r"GPU Memory Allocated \(VRAM%\):\s*([0-9.]+)", output)
    return gpu_util, vram_percent


def _latest_lora_progress(log_text: str) -> dict[str, Any] | None:
    # TQDM writes carriage-return progress lines; search the whole tail chunk.
    pattern = re.compile(
        r"(?P<step>\d+)/(?:\s*)?(?P<total>\d+)\s*"
        r"\[(?P<elapsed>[^\]<]+)<(?P<eta>[^,\]]+),\s*"
        r"(?P<seconds>[0-9.]+)s/it,\s*lr:\s*(?P<lr>[0-9.eE+-]+)\s*loss:\s*(?P<loss>[0-9.eE+-]+)"
    )
    matches = list(pattern.finditer(log_text))
    if not matches:
        return None
    match = matches[-1]
    step = int(match.group("step"))
    total = int(match.group("total"))
    return {
        "current_step": step,
        "total_steps": total,
        "progress_percent": round((step / total) * 100, 2) if total else None,
        "loss": float(match.group("loss")),
        "lr": float(match.group("lr")),
        "elapsed": match.group("elapsed"),
        "eta": match.group("eta"),
        "seconds_per_step": float(match.group("seconds")),
    }


@app.post("/api/lora-training/start", response_model=LoraTrainingStartResponse)
async def lora_training_start(body: LoraTrainingStartRequest) -> LoraTrainingStartResponse:
    # Build the config from template
    config_path, _ = _build_training_config(body)

    job_name = body.job_name
    log_path = _TRAINING_DIR / "logs" / f"{job_name}.log"
    output_dir = _TRAINING_DIR / "output" / job_name

    log_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write active job state so status/checkpoints pick up the new job
    _write_active_job({
        "job_name": job_name,
        "log_path": str(log_path),
        "output_dir": str(output_dir),
        "config_path": str(config_path),
        "dataset": body.dataset,
        "trigger_word": body.trigger_word,
        "model": body.model,
        "started_at": datetime.now(UTC).isoformat(),
    })

    # Spawn ai-toolkit in the background
    try:
        with open(log_path, "w") as log_file:
            subprocess.Popen(
                [_TRAINING_RUNNER, str(config_path)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as exc:
        return LoraTrainingStartResponse(
            ok=False,
            job_name=job_name,
            status="error",
            config_path=str(config_path),
            log_path=str(log_path),
            output_dir=str(output_dir),
            error=str(exc),
        )

    return LoraTrainingStartResponse(
        ok=True,
        job_name=job_name,
        status="started",
        config_path=str(config_path),
        log_path=str(log_path),
        output_dir=str(output_dir),
    )


@app.get("/api/lora-training/status", response_model=LoraTrainingStatus)
async def lora_training_status(job_name: str | None = None) -> LoraTrainingStatus:
    resolved_name, log_path, output_dir = _resolve_job_context(job_name)
    gpu_util, vram_percent = _read_gpu_status()
    updated_at = datetime.now(UTC).isoformat()

    if not log_path.exists():
        return LoraTrainingStatus(
            ok=False,
            status="missing_log",
            job_name=resolved_name,
            gpu_util=gpu_util,
            vram_percent=vram_percent,
            log_path=str(log_path),
            updated_at=updated_at,
            error="Training log not found",
        )

    try:
        log_text = log_path.read_text(errors="replace")[-200_000:]
    except Exception as exc:
        return LoraTrainingStatus(
            ok=False,
            status="error",
            job_name=resolved_name,
            gpu_util=gpu_util,
            vram_percent=vram_percent,
            log_path=str(log_path),
            updated_at=updated_at,
            error=str(exc),
        )

    progress = _latest_lora_progress(log_text)
    if not progress:
        status = "starting" if "Running job" in log_text else "unknown"
        return LoraTrainingStatus(
            ok=True,
            status=status,
            job_name=resolved_name,
            gpu_util=gpu_util,
            vram_percent=vram_percent,
            log_path=str(log_path),
            updated_at=updated_at,
        )

    current_step = progress["current_step"]
    total_steps = progress["total_steps"]
    final_checkpoint = output_dir / f"{resolved_name}.safetensors"

    completed = current_step >= total_steps
    completed = completed or final_checkpoint.is_file()
    completed = completed or "Done training" in log_text or "Training complete" in log_text
    status = "completed" if completed else "training"

    if completed and final_checkpoint.is_file() and current_step < total_steps:
        progress = {**progress, "current_step": total_steps, "progress_percent": 100.0, "eta": "00:00"}

    job_state = _active_job_state()
    started_at = job_state.get("started_at")
    finished_at = job_state.get("finished_at")
    total_duration_seconds = job_state.get("total_duration_seconds")

    if completed and not finished_at:
        finished_at = updated_at
        if started_at:
            try:
                from datetime import datetime as _dt
                delta = _dt.fromisoformat(finished_at) - _dt.fromisoformat(started_at)
                total_duration_seconds = round(delta.total_seconds(), 1)
            except Exception:
                pass
        _write_active_job({**job_state, "finished_at": finished_at, "total_duration_seconds": total_duration_seconds})

    return LoraTrainingStatus(
        ok=True,
        status=status,
        job_name=resolved_name,
        gpu_util=gpu_util,
        vram_percent=vram_percent,
        log_path=str(log_path),
        started_at=started_at,
        finished_at=finished_at,
        total_duration_seconds=total_duration_seconds,
        updated_at=updated_at,
        **progress,
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

    graph = build_flux2_lora_image(
        prompt=prompt,
        loras=loras,
        width=body.width,
        height=body.height,
        seed=body.seed,
        filename_prefix=body.filename_prefix,
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
    resolved_name, _, output_dir = _resolve_job_context(job_name)
    updated_at = datetime.now(UTC).isoformat()
    checkpoints: list[LoraCheckpoint] = []

    if output_dir.is_dir():
        for path in sorted(output_dir.glob("*.safetensors")):
            stat = path.stat()
            step_match = re.search(r"_(\d{6,})\.safetensors$", path.name)
            checkpoints.append(
                LoraCheckpoint(
                    name=path.name,
                    step=int(step_match.group(1)) if step_match else None,
                    path=str(path),
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                )
            )

    checkpoints.sort(key=lambda item: item.step if item.step is not None else -1)
    return LoraCheckpointsResponse(
        ok=True,
        job_name=resolved_name,
        checkpoints=checkpoints,
        count=len(checkpoints),
        updated_at=updated_at,
    )


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
    return {"ok": not failed, "deleted": deleted, "failed": failed}

