from __future__ import annotations

import time
from typing import Any, Literal

WAN_NEGATIVE = (
    "bright colors, overexposed, static, blurred details, subtitles, style, artwork, "
    "painting, still image, overall gray, worst quality, low quality, JPEG artifacts, "
    "ugly, deformed, extra fingers, poorly drawn hands, poorly drawn face, malformed, "
    "disfigured, bad anatomy"
)


def _seed(seed: int | None) -> int:
    return int(time.time()) if seed is None else seed


def build_wan22_t2v(
    *,
    prompt: str,
    negative: str = WAN_NEGATIVE,
    width: int = 1280,
    height: int = 720,
    length: int = 121,
    fps: int = 16,
    seed: int | None = None,
    filename_prefix: str = "videos/generated",
    steps_high: int = 2,
    steps_low: int = 2,
    cfg_high: float = 3.5,
    cfg_low: float = 3.5,
    shift: float = 5.0,
    sampler: str = "euler",
    scheduler: str = "simple",
) -> dict:
    """Build native ComfyUI API-format JSON for Wan 2.2 text-to-video."""

    total_steps = steps_high + steps_low
    noise_seed = _seed(seed)
    return {
        "90": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "91": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "80": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["90", 0], "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors", "strength_model": 1.0}},
        "82": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["91", 0], "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors", "strength_model": 1.0}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["38", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["38", 0]}},
        "63": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"width": width, "height": height, "length": length, "batch_size": 1}},
        "54": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["80", 0], "shift": shift}},
        "55": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["82", 0], "shift": shift}},
        "57": {"class_type": "KSamplerAdvanced", "inputs": {"add_noise": "enable", "noise_seed": noise_seed, "control_after_generate": "randomize", "steps": total_steps, "cfg": cfg_high, "sampler_name": sampler, "scheduler": scheduler, "start_at_step": 0, "end_at_step": steps_high, "return_with_leftover_noise": "enable", "model": ["54", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["63", 0]}},
        "58": {"class_type": "KSamplerAdvanced", "inputs": {"add_noise": "disable", "noise_seed": 0, "control_after_generate": "fixed", "steps": total_steps, "cfg": cfg_low, "sampler_name": sampler, "scheduler": scheduler, "start_at_step": steps_high, "end_at_step": 10000, "return_with_leftover_noise": "disable", "model": ["55", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["57", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["58", 0], "vae": ["39", 0]}},
        "60": {"class_type": "CreateVideo", "inputs": {"fps": fps, "images": ["8", 0]}},
        "61": {"class_type": "SaveVideo", "inputs": {"filename_prefix": filename_prefix, "format": "auto", "codec": "h264", "video": ["60", 0]}},
    }


def build_flux2_lora_image(
    *,
    prompt: str,
    lora_name: str | None = None,
    loras: list[dict[str, Any]] | None = None,
    width: int = 1248,
    height: int = 832,
    seed: int | None = None,
    filename_prefix: str = "images/generated",
    steps: int = 20,
    cfg: float = 4.0,
    sampler: str = "euler",
    guidance: float = 4.0,
    unet: str = "flux2_dev_fp8mixed.safetensors",
    clip: str = "mistral_3_small_flux2_bf16.safetensors",
    vae: str = "flux2-vae.safetensors",
    lora_strength: float = 1.0,
) -> dict:
    """Build native ComfyUI API-format JSON for FLUX.2 text-to-image with a LoRA.

    Reference workflow: ComfyUI workflow-templates `templates-all_in_one-image_edit_models.json`,
    FLUX.2 dev subgraph (`UNETLoader` + `CLIPLoader type=flux2` + `Flux2Scheduler`
    + `SamplerCustomAdvanced`).
    """

    noise_seed = _seed(seed)
    lora_specs = list(loras or [])
    if lora_name:
        lora_specs.insert(0, {"name": lora_name, "strength": lora_strength})

    workflow = {
        "12": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "flux2", "device": "default"}},
        "10": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["38", 0]}},
        "26": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["6", 0], "guidance": guidance}},
        "25": {"class_type": "RandomNoise", "inputs": {"noise_seed": noise_seed}},
        "16": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler}},
        "48": {"class_type": "Flux2Scheduler", "inputs": {"steps": steps, "width": width, "height": height}},
        "47": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "13": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["25", 0], "guider": ["22", 0], "sampler": ["16", 0], "sigmas": ["48", 0], "latent_image": ["47", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["10", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": filename_prefix}},
    }

    model_ref = ["12", 0]
    for index, spec in enumerate(lora_specs, start=1):
        name = spec.get("name") or spec.get("lora_name")
        if not name:
            continue
        node_id = str(50 + index)
        workflow[node_id] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": model_ref, "lora_name": name, "strength_model": float(spec.get("strength", lora_strength))},
        }
        model_ref = [node_id, 0]

    workflow["22"] = {"class_type": "BasicGuider", "inputs": {"model": model_ref, "conditioning": ["26", 0]}}
    return workflow



def build_wan22_i2v(
    *,
    image: str,
    prompt: str,
    negative: str = WAN_NEGATIVE,
    width: int = 1280,
    height: int = 720,
    length: int = 121,
    fps: int = 16,
    seed: int | None = None,
    filename_prefix: str = "videos/generated",
    steps_high: int = 2,
    steps_low: int = 2,
    cfg_high: float = 3.5,
    cfg_low: float = 3.5,
    shift: float = 5.0,
    sampler: str = "euler",
    scheduler: str = "simple",
    high_model: str = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
    low_model: str = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
    vae: str = "wan_2.1_vae.safetensors",
    clip: str = "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
    lightx2v_high: str | None = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
    lightx2v_low: str | None = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
    high_lora: str | None = None,
    low_lora: str | None = None,
    high_lora_strength: float = 1.0,
    low_lora_strength: float = 1.0,
) -> dict:
    """Build native ComfyUI API-format JSON for Wan 2.2 image-to-video."""

    total_steps = steps_high + steps_low
    noise_seed = _seed(seed)
    high_model_ref = ["90", 0]
    low_model_ref = ["91", 0]
    workflow = {
        "90": {"class_type": "UNETLoader", "inputs": {"unet_name": high_model, "weight_dtype": "default"}},
        "91": {"class_type": "UNETLoader", "inputs": {"unet_name": low_model, "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["38", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["38", 0]}},
        "62": {"class_type": "LoadImage", "inputs": {"image": image}},
        "63": {"class_type": "WanImageToVideo", "inputs": {"positive": ["6", 0], "negative": ["7", 0], "vae": ["39", 0], "start_image": ["62", 0], "width": width, "height": height, "length": length, "batch_size": 1}},
    }
    # LightX2V 4-step speed LoRAs — applied first to base model before character LoRAs
    if lightx2v_high:
        workflow["83"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": high_model_ref, "lora_name": lightx2v_high, "strength_model": 1.0}}
        high_model_ref = ["83", 0]
    if lightx2v_low:
        workflow["84"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": low_model_ref, "lora_name": lightx2v_low, "strength_model": 1.0}}
        low_model_ref = ["84", 0]
    # Character LoRAs — chained on top of LightX2V
    if high_lora:
        workflow["80"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": high_model_ref, "lora_name": high_lora, "strength_model": high_lora_strength}}
        high_model_ref = ["80", 0]
    if low_lora:
        workflow["82"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": low_model_ref, "lora_name": low_lora, "strength_model": low_lora_strength}}
        low_model_ref = ["82", 0]

    workflow.update({
        "54": {"class_type": "ModelSamplingSD3", "inputs": {"model": high_model_ref, "shift": shift}},
        "55": {"class_type": "ModelSamplingSD3", "inputs": {"model": low_model_ref, "shift": shift}},
        "57": {"class_type": "KSamplerAdvanced", "inputs": {"add_noise": "enable", "noise_seed": noise_seed, "control_after_generate": "randomize", "steps": total_steps, "cfg": cfg_high, "sampler_name": sampler, "scheduler": scheduler, "start_at_step": 0, "end_at_step": steps_high, "return_with_leftover_noise": "enable", "model": ["54", 0], "positive": ["63", 0], "negative": ["63", 1], "latent_image": ["63", 2]}},
        "58": {"class_type": "KSamplerAdvanced", "inputs": {"add_noise": "disable", "noise_seed": 0, "control_after_generate": "fixed", "steps": total_steps, "cfg": cfg_low, "sampler_name": sampler, "scheduler": scheduler, "start_at_step": steps_high, "end_at_step": 10000, "return_with_leftover_noise": "disable", "model": ["55", 0], "positive": ["63", 0], "negative": ["63", 1], "latent_image": ["57", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["58", 0], "vae": ["39", 0]}},
        "60": {"class_type": "CreateVideo", "inputs": {"fps": fps, "images": ["8", 0]}},
        "61": {"class_type": "SaveVideo", "inputs": {"filename_prefix": filename_prefix, "format": "auto", "codec": "h264", "video": ["60", 0]}},
    })
    return workflow
