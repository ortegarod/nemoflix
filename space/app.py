import os
from pathlib import Path

import gradio as gr
import requests

NEMOFLIX_API_URL = os.environ.get("NEMOFLIX_API_URL", "").rstrip("/")
REQUEST_TIMEOUT = 30


def require_backend() -> str:
    if not NEMOFLIX_API_URL:
        raise gr.Error("NEMOFLIX_API_URL is not configured. Add it as a Space secret.")
    return NEMOFLIX_API_URL


def api_url(path: str) -> str:
    return f"{require_backend()}{path}"


def health_check():
    try:
        response = requests.get(api_url("/api/health"), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return "✅ Backend online", response.json()
    except Exception as exc:
        return f"❌ Backend unavailable: {exc}", None


def upload_image(image_path: str) -> str:
    if not image_path:
        raise gr.Error("Upload an image for image-to-video mode.")

    with open(image_path, "rb") as fh:
        files = {"file": (Path(image_path).name, fh, "application/octet-stream")}
        response = requests.post(api_url("/api/images/upload"), files=files, timeout=REQUEST_TIMEOUT)

    response.raise_for_status()
    data = response.json()
    image_name = data.get("image") or data.get("comfy", {}).get("name")
    if not image_name:
        raise gr.Error(f"Upload succeeded, but no image name was returned: {data}")
    return image_name


def submit_generation(mode, image_path, prompt, width, height, length, fps, steps_high, steps_low, cfg, consent):
    if not prompt or not prompt.strip():
        raise gr.Error("Prompt is required.")
    if not consent:
        raise gr.Error("Confirm you own or have permission to use the image/likeness before generating.")

    payload = {
        "mode": mode,
        "prompt": prompt.strip(),
        "width": int(width),
        "height": int(height),
        "length": int(length),
        "fps": int(fps),
        "steps_high": int(steps_high),
        "steps_low": int(steps_low),
        "cfg_high": float(cfg),
        "cfg_low": float(cfg),
        "filename_prefix": "nemoflix-space/video",
    }

    if mode == "i2v":
        payload["image"] = upload_image(image_path)

    response = requests.post(api_url("/api/video/generate"), json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise gr.Error(f"Backend did not return a prompt_id: {data}")

    return prompt_id, f"Queued job: {prompt_id}", data


def check_job(prompt_id):
    if not prompt_id:
        raise gr.Error("Submit a job first, or paste a prompt_id.")

    response = requests.get(api_url(f"/api/jobs/{prompt_id}"), timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    outputs = data.get("outputs", [])
    video_url = None
    for output in outputs:
        if output.get("type") == "video" and output.get("url"):
            video_url = output["url"]
            break

    status_parts = [data.get("status", "unknown")]
    if data.get("progress") is not None:
        status_parts.append(f"{data['progress']}%")
    if data.get("queue_position") is not None:
        status_parts.append(f"queue position {data['queue_position']}")
    if data.get("outputs_count") is not None:
        status_parts.append(f"outputs {data['outputs_count']}")
    return " · ".join(status_parts), video_url, data


with gr.Blocks(title="Nemoflix AMD Video") as demo:
    gr.Markdown(
        """
# Nemoflix AMD Video

AI-agent-native video generation backed by a real Nemoflix API running against ComfyUI on AMD hardware.

Generation requires a live Nemoflix backend. If the backend is unavailable, generation is unavailable.
"""
    )

    with gr.Row():
        health_button = gr.Button("Check backend")
        health_text = gr.Textbox(label="Backend status", interactive=False)
    health_json = gr.JSON(label="Backend health")
    health_button.click(fn=health_check, outputs=[health_text, health_json])

    with gr.Row():
        mode = gr.Radio(["t2v", "i2v"], value="t2v", label="Mode")
        image = gr.Image(label="Source image for image-to-video", type="filepath")

    prompt = gr.Textbox(
        label="Prompt",
        lines=4,
        placeholder="cinematic shot, subject walking through neon rain, dramatic lighting",
    )

    consent = gr.Checkbox(
        label="I confirm I own or have permission to use the uploaded image, likeness, and prompt content.",
        value=False,
    )

    with gr.Row():
        width = gr.Number(label="Width", value=640, precision=0)
        height = gr.Number(label="Height", value=640, precision=0)
        length = gr.Number(label="Frames", value=33, precision=0)
        fps = gr.Number(label="FPS", value=16, precision=0)

    with gr.Row():
        steps_high = gr.Number(label="High-noise steps", value=2, precision=0)
        steps_low = gr.Number(label="Low-noise steps", value=2, precision=0)
        cfg = gr.Number(label="CFG", value=1.0)

    generate_button = gr.Button("Generate video", variant="primary")
    prompt_id = gr.Textbox(label="Prompt ID")
    submit_status = gr.Textbox(label="Submit status", interactive=False)
    submit_details = gr.JSON(label="Submit response")

    generate_button.click(
        fn=submit_generation,
        inputs=[mode, image, prompt, width, height, length, fps, steps_high, steps_low, cfg, consent],
        outputs=[prompt_id, submit_status, submit_details],
    )

    check_button = gr.Button("Refresh job status")
    job_status = gr.Textbox(label="Job status", interactive=False)
    video = gr.Video(label="Generated video")
    job_details = gr.JSON(label="Job details")

    check_button.click(fn=check_job, inputs=[prompt_id], outputs=[job_status, video, job_details])

if __name__ == "__main__":
    demo.launch()
