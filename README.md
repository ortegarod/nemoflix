# Nemoflix

Agent-native image and video generation studio powered by ComfyUI and AMD GPUs.

## What It Is

Agents call a REST API; Nemoflix builds and submits ComfyUI workflows behind the scenes. Includes a Studio UI for human-in-the-loop editing.

## Features

- Image generation with Flux2 + character LoRAs
- Video generation with Wan 2.2 (text-to-video and image-to-video)
- Flux2 identity LoRA training on AMD MI300X
- Projects → scenes → shots with version history
- Persistent character profiles with LoRA associations
- React/Vite Studio UI

## Architecture

| Layer | Technology |
|---|---|
| API | FastAPI (Python) |
| Generation engine | ComfyUI |
| Training | Ostris AI Toolkit (ROCm) |
| Studio UI | React + Vite |
| Database | PostgreSQL |
| Target GPU | AMD Instinct MI300X, ROCm 7.2 |


## Getting Started

### AMD Developer Cloud (ROCm 7.2 droplet)

Paste `scripts/startup-script.sh` into the droplet's user data field when provisioning. It clones the repo, installs ComfyUI, the API, required models, and starts all services.

### Configuration

Copy `.env.example` to `.env`:

| Variable | Description |
|---|---|
| `COMFY_URL` | ComfyUI base URL |
| `DATABASE_URL` | PostgreSQL connection string |
| `AITK_API_URL` | AI Toolkit API URL |
| `NEMOFLIX_OUTPUT_DIR` | Output directory |
| `ELEVENLABS_API_KEY` | TTS — optional |

GPU node routing lives in `config.json`.

## Usage

### Studio UI

A React/Vite interface for managing characters, projects, scenes, shots, and generation jobs.

```bash
cd studio && npm install && npm run dev
```

### API

Set `COMFY_URL` to point at your ComfyUI instance.

```bash
# Health
curl http://<your-host>:8190/api/health

# Generate image
curl -X POST http://<your-host>:8190/api/image/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a man standing on a cliff overlooking the ocean at sunset, warm golden light, waves crashing below, photorealistic", "width": 1024, "height": 1024}'

# Check job
curl http://<your-host>:8190/api/jobs/<prompt_id>
```

## LoRA Training

### Prepare

Add reference images to `/root/nemoflix-training/datasets/<run-name>/`, then register the dataset:

```bash
curl -X POST http://<your-host>:8190/api/lora-training/datasets \
  -H "Content-Type: application/json" \
  -d '{"id": "<run-name>", "name": "My Character"}'
```

### Train

Submit a training job through the API. Nemoflix builds the config internally — you just describe the job:

```bash
curl -X POST http://<your-host>:8190/api/lora-training/start \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-character-v1",
    "trigger_word": "mycharacter",
    "dataset": "my-character",
    "base_config": "flux2_identity",
    "model": "flux2_dev"
  }'
```

Training runs on the AMD GPU. Monitor progress with `GET /api/lora-training/status` — checkpoints appear at `GET /api/lora-training/checkpoints` as they complete.

## Contributing

Issues and PRs welcome. Test against a ROCm environment if touching generation or training code.

## License

Apache 2.0 — see [LICENSE](LICENSE).
