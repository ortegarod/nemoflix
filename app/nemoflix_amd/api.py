from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import websockets

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .comfy import ComfyClient
from .config import get_settings
from .workflows import WAN_NEGATIVE, build_wan22_i2v, build_wan22_t2v

app = FastAPI(
    title="Nemoflix AMD API",
    description="Agent-native API for driving ComfyUI video generation on AMD GPUs.",
    version="0.1.0",
)


class VideoGenerateRequest(BaseModel):
    mode: Literal["t2v", "i2v"] = "i2v"
    prompt: str = Field(min_length=1)
    image: str | None = Field(default=None, description="ComfyUI input filename for image-to-video")
    negative: str = WAN_NEGATIVE
    width: int = 1280
    height: int = 720
    length: int = Field(default=121, description="Frame count, not seconds")
    fps: int = 16
    seed: int | None = None
    filename_prefix: str = "nemoflix-amd/video"
    steps_high: int = 10
    steps_low: int = 10
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


def comfy() -> ComfyClient:
    settings = get_settings()
    return ComfyClient(settings.comfy_url, settings.request_timeout_seconds)


_JOBS: dict[str, dict[str, Any]] = {}
_COMFY_CLIENT_ID = "nemoflix-amd-gallery"
_WS_TASK: asyncio.Task | None = None


def _ws_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, "/ws", "", f"clientId={_COMFY_CLIENT_ID}", ""))


def _register_submitted_job(prompt_id: str | None, body: VideoGenerateRequest, status: str = "pending") -> None:
    if not prompt_id:
        return
    _JOBS[prompt_id] = {
        "prompt_id": prompt_id,
        "status": status,
        "mode": body.mode,
        "prompt": body.prompt,
        "width": body.width,
        "height": body.height,
        "length": body.length,
        "fps": body.fps,
        "created_at": datetime.now(UTC).isoformat(),
        "current_node": None,
        "step_value": 0,
        "step_max": 0,
        "nodes_finished": 0,
        "nodes_total": 0,
        "progress_percent": None,
    }


def _update_job_from_progress_state(prompt_id: str, nodes: dict[str, Any]) -> None:
    if not prompt_id:
        return
    job = _JOBS.setdefault(prompt_id, {"prompt_id": prompt_id, "status": "running", "created_at": None})
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
    job.update({
        "status": "running",
        "nodes_total": total,
        "nodes_finished": finished,
        "nodes_running": running,
        "current_node": current_node,
        "step_value": step_value,
        "step_max": step_max,
        "progress_percent": percent,
        "updated_at": datetime.now(UTC).isoformat(),
    })


async def _comfy_ws_bridge() -> None:
    settings = get_settings()
    url = _ws_url(settings.comfy_url)
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
                        _JOBS.setdefault(prompt_id, {"prompt_id": prompt_id, "created_at": None}).update({"status": "running"})
                    elif msg_type == "progress_state" and isinstance(prompt_id, str):
                        nodes = data.get("nodes", {})
                        if isinstance(nodes, dict):
                            _update_job_from_progress_state(prompt_id, nodes)
                    elif msg_type == "progress" and isinstance(prompt_id, str):
                        job = _JOBS.setdefault(prompt_id, {"prompt_id": prompt_id, "status": "running", "created_at": None})
                        value = int(data.get("value") or 0)
                        max_value = int(data.get("max") or 0)
                        job.update({
                            "status": "running",
                            "step_value": value,
                            "step_max": max_value,
                            "progress_percent": round((value / max_value) * 100, 1) if max_value else None,
                            "updated_at": datetime.now(UTC).isoformat(),
                        })
                    elif msg_type == "execution_success" and isinstance(prompt_id, str):
                        _JOBS.setdefault(prompt_id, {"prompt_id": prompt_id, "created_at": None}).update({
                            "status": "completed",
                            "progress_percent": 100,
                            "updated_at": datetime.now(UTC).isoformat(),
                        })
                    elif msg_type in {"execution_error", "execution_interrupted"} and isinstance(prompt_id, str):
                        _JOBS.setdefault(prompt_id, {"prompt_id": prompt_id, "created_at": None}).update({
                            "status": "failed",
                            "error": data.get("exception_message") or msg_type,
                            "updated_at": datetime.now(UTC).isoformat(),
                        })
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(3)


@app.on_event("startup")
async def start_comfy_bridge() -> None:
    global _WS_TASK
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


@app.get("/api/health")
async def health() -> dict[str, Any]:
    client = comfy()
    try:
        stats = await client.get("/system_stats")
    except Exception as exc:  # noqa: BLE001 - return service health, not stack trace
        raise HTTPException(status_code=502, detail=f"ComfyUI unavailable: {exc}") from exc
    return {"ok": True, "comfy_url": client.base_url, "system_stats": stats}


@app.get("/api/comfy/{path:path}")
async def comfy_get(path: str) -> Any:
    """Read-only passthrough for Comfy discovery endpoints: models, queue, object_info, history, etc."""
    allowed_roots = ("system_stats", "object_info", "models", "queue", "history", "prompt", "features")
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
    if body.mode == "i2v":
        if not body.image:
            raise HTTPException(status_code=400, detail="image is required for i2v mode. Upload first with /api/images/upload.")
        workflow = build_wan22_i2v(
            image=body.image,
            prompt=body.prompt,
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
            high_lora=body.high_lora,
            low_lora=body.low_lora,
            high_lora_strength=body.high_lora_strength,
            low_lora_strength=body.low_lora_strength,
        )
    else:
        workflow = build_wan22_t2v(
            prompt=body.prompt,
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
        result = await comfy().queue_prompt(workflow, client_id=_COMFY_CLIENT_ID)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ComfyUI prompt submission failed: {exc}") from exc

    prompt_id = result.get("prompt_id")
    _register_submitted_job(prompt_id, body, "pending")
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


async def _queue_position(client: ComfyClient, prompt_id: str) -> int | None:
    queue = await client.get("/queue")
    pending = queue.get("queue_pending", []) if isinstance(queue, dict) else []
    for index, item in enumerate(pending, start=1):
        if isinstance(item, list) and len(item) > 1 and item[1] == prompt_id:
            return index
    return None


@app.get("/api/jobs")
async def jobs() -> dict[str, Any]:
    """Return jobs submitted through this API.

    ComfyUI is still the execution engine, but this endpoint intentionally does
    not list arbitrary Comfy queue entries. The gallery should only show jobs we
    submitted and registered locally; completed media is discovered separately by
    /api/listing.
    """
    client = comfy()

    try:
        queue = await client.get("/queue")
    except Exception as exc:  # noqa: BLE001
        jobs_list = sorted(_JOBS.values(), key=lambda j: j.get("created_at") or "", reverse=True)
        return {"jobs": jobs_list, "count": len(jobs_list), "error": str(exc)}

    running_ids: set[str] = set()
    pending_positions: dict[str, int] = {}

    for item in queue.get("queue_running", []) if isinstance(queue, dict) else []:
        if isinstance(item, list) and len(item) > 1 and isinstance(item[1], str):
            running_ids.add(item[1])

    for position, item in enumerate(queue.get("queue_pending", []) if isinstance(queue, dict) else [], start=1):
        if isinstance(item, list) and len(item) > 1 and isinstance(item[1], str):
            pending_positions[item[1]] = position

    for prompt_id, job in _JOBS.items():
        if job.get("status") in {"completed", "failed"}:
            continue
        if prompt_id in running_ids:
            job["status"] = "running"
            job["queue_position"] = None
        elif prompt_id in pending_positions:
            job["status"] = "pending"
            job["queue_position"] = pending_positions[prompt_id]
        elif job.get("status") in {"pending", "running"}:
            job["status"] = "unknown"
            job["queue_position"] = None

    jobs_list = sorted(
        _JOBS.values(),
        key=lambda j: (j.get("status") != "running", j.get("queue_position") or 0, j.get("created_at") or ""),
    )
    return {"jobs": jobs_list, "count": len(jobs_list)}


@app.get("/api/jobs/{prompt_id}", response_model=JobStatusResponse)
async def job(prompt_id: str) -> JobStatusResponse:
    client = comfy()

    # ComfyUI's normalized jobs endpoint reports pending/in_progress/completed.
    # It is the right polling surface for UI status. Raw /history only exists after completion.
    try:
        comfy_job = await client.get(f"/api/jobs/{prompt_id}")
        outputs = _extract_outputs_from_comfy_job(comfy_job, client)
        status = comfy_job.get("status", "unknown")
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
        status = "completed" if outputs else ("queued_or_running" if history == {} else "unknown")
        progress = 100.0 if outputs else None
        return JobStatusResponse(ok=True, prompt_id=prompt_id, status=status, progress=progress, outputs=outputs, raw=history)


import os
from fastapi.responses import FileResponse

_OUTPUT_DIR = Path("/root/ComfyUI/output")
_ALLOW_EXT = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".gif"}


@app.get("/api/listing")
async def listing(dir: str = "", offset: int = 0, limit: int = 60) -> dict[str, Any]:
    base = _OUTPUT_DIR / dir if dir else _OUTPUT_DIR
    if not str(base.resolve()).startswith(str(_OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=400, detail="Invalid dir")
    items: list[dict[str, Any]] = []
    total = 0

    def scan_directory(scan_base: Path, rel_prefix: str = ""):
        nonlocal total
        if not scan_base.is_dir():
            return
        for entry in scan_base.iterdir():
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                new_prefix = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                scan_directory(entry, new_prefix)
            elif entry.is_file():
                ext = entry.suffix.lower()
                if ext not in _ALLOW_EXT:
                    continue
                total += 1
                if len(items) >= limit:
                    continue
                w, h = 0, 0
                if ext in {".mp4", ".webm"}:
                    w, h = 1280, 720
                else:
                    try:
                        from PIL import Image
                        with Image.open(entry) as im:
                            w, h = im.width, im.height
                    except Exception:
                        pass
                rel = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                item: dict[str, Any] = {
                    "name": entry.name,
                    "type": "video" if ext in {".mp4", ".webm", ".gif"} else "image",
                    "width": w,
                    "height": h,
                    "mtime": entry.stat().st_mtime,
                    "url": f"/media/{rel}",
                    "thumb": f"/media/{rel}",
                }
                items.append(item)

    scan_directory(base)
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"images": items, "total": total, "offset": offset, "limit": limit}


@app.get("/media/{path:path}")
async def media(path: str) -> FileResponse:
    target = _OUTPUT_DIR / path
    if not str(target.resolve()).startswith(str(_OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    stat = target.stat()
    etag = f'W/"{stat.st_mtime_ns}-{stat.st_size}"'
    return FileResponse(
        target,
        headers={"Cache-Control": "private, max-age=604800, immutable", "ETag": etag},
    )

