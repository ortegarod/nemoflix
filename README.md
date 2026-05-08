# Nemoflix

Agent-native image and video generation using ComfyUI as a headless execution engine.

Nemoflix is designed for AI agents first. Agents call a simple HTTP API; Nemoflix builds and submits ComfyUI workflows behind the scenes. ComfyUI's browser UI is not part of the workflow.

## What this repo does now

- Starts a small FastAPI service for agent-driven generation
- Talks to ComfyUI through its native HTTP API
- Trains Flux2 identity LoRAs on AMD MI300X and monitors training progress
- Generates images with character LoRAs through Flux2
- Builds Wan 2.2 video workflow JSON in code
- Supports text-to-video and image-to-video requests


## API

Default local service ports:

| Service | Port |
| --- | ---: |
| ComfyUI | `8188` |
| Nemoflix API | `8190` |

### Health

```bash
curl -sS http://127.0.0.1:8190/api/health
```

### LoRA training status

```bash
curl -sS http://127.0.0.1:8190/api/lora-training/status
curl -sS http://127.0.0.1:8190/api/lora-training/checkpoints
```

### Upload image

```bash
curl -sS -X POST http://127.0.0.1:8190/api/images/upload \
  -F "file=@/path/to/source.png"
```

### Generate image-to-video

```bash
curl -sS -X POST http://127.0.0.1:8190/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "i2v",
    "image": "source.png",
    "prompt": "cinematic shot, subject walking through neon rain",
    "width": 1280,
    "height": 720,
    "length": 121,
    "fps": 16
  }'
```

### Generate text-to-video

```bash
curl -sS -X POST http://127.0.0.1:8190/api/video/generate \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "t2v",
    "prompt": "cinematic tracking shot through a futuristic city at night",
    "width": 1280,
    "height": 720,
    "length": 121,
    "fps": 16
  }'
```

### Check job

```bash
curl -sS http://127.0.0.1:8190/api/jobs/<prompt_id>
```

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=app uvicorn nemoflix_amd.api:app --host 0.0.0.0 --port 8190
```

Point the API at a ComfyUI server with:

```bash
export COMFY_URL=http://127.0.0.1:8188
```

## Repo structure

```text
app/nemoflix_amd/          # API service and workflow builders
scripts/                   # optional deployment/setup helpers
research/                  # research notes
training/                  # local training data and outputs, gitignored
  datasets/                # prepared training datasets per run
  output/                  # LoRA / model training outputs
outputs/                   # generated outputs, gitignored
```

## Hackathon infrastructure

This repo is being built for the AMD Developer Hackathon and currently targets the AMD GPU Developer Cloud environment available through DigitalOcean GPU Droplets.

Reference hardware:

| Resource | Spec |
| --- | --- |
| GPU | 1x AMD Instinct MI300X |
| VRAM | 192 GB |
| vCPU | 20 |
| RAM | 240 GB |
| Boot disk | 720 GB NVMe SSD |
| Scratch disk | 5 TB NVMe SSD |
| GPU software | ROCm 7.2 image |
| Cost | About $1.99/GPU-hour |

The setup scripts assume a fresh Ubuntu ROCm droplet and install ComfyUI plus the Nemoflix API service.
