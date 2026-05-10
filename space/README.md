---
title: NemoFlix
emoji: 🎬
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: true
short_description: Train a LoRA, generate images, animate into AI films.
tags:
  - amd
  - amd-hackathon-2026
  - comfyui
  - video-generation
  - lora
  - ai-video
  - image-generation
  - flux
  - wan
  - agent-native
  - self-hosted

---

# Nemoflix

**Nemoflix** is an open, self-hostable, API-first media studio for AI agents.

Upload a few photos, train a Flux.2 LoRA of yourself or any character (~90 min on AMD MI300X), then generate photorealistic images and animate them into short films with Wan 2.2 I2V. One consistent identity across every frame.

## What it does

- **Train** — Fine-tune a Flux.2 LoRA from 15–25 reference photos (ROCm, no CUDA required)
- **Generate** — Photorealistic images with your trained identity in any scene
- **Animate** — Image-to-video with Wan 2.2 I2V (14B, fp8 scaled, LightX2V 2-step)
- **Direct** — Assemble scenes, shots, and final cuts in a project timeline


## Required Space secrets

| Secret | Description |
| --- | --- |
| `NEMOFLIX_API_URL` | URL of your Nemoflix backend API (e.g. `http://your-vps:8190`) |
