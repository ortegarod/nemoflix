---
title: Nemoflix AMD Video
emoji: 🎬
colorFrom: red
colorTo: yellow
sdk: gradio
sdk_version: 5.29.0
app_file: app.py
pinned: false
tags:
  - amd
  - amd-hackathon-2026
  - gradio
  - comfyui
  - video-generation
---

# Nemoflix AMD Video

A Gradio interface for AI-agent-native video generation backed by a Nemoflix API running ComfyUI on AMD GPU infrastructure.

## Required Space secret

| Secret | Description |
| --- | --- |
| `NEMOFLIX_API_URL` | Public URL for the Nemoflix API, for example `http://YOUR_DROPLET_IP:8190` |

## Behavior

Generation requires a live Nemoflix backend. If the backend is unavailable, the app shows that generation is unavailable.

The app requires explicit confirmation that the user owns or has permission to use uploaded images, likenesses, and prompt content.
