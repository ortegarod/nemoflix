#!/bin/bash
set -Eeuo pipefail
set -x

COMFY_DIR="${COMFY_DIR:-/root/ComfyUI}"
COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
NEMOFLIX_API_URL="${NEMOFLIX_API_URL:-http://127.0.0.1:8190}"
HF_BASE_FLUX2="https://huggingface.co/Comfy-Org/flux2-dev/resolve/main/split_files"
HF_BASE_Z_IMAGE="https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files"
RUN_IMAGE_STACK_TEST="${RUN_IMAGE_STACK_TEST:-0}"
IMAGE_STACK_TEST_PROMPT="${IMAGE_STACK_TEST_PROMPT:-realistic social media creator photo, confident person filming lifestyle content, modern studio setup, smartphone camera, soft natural light, polished Instagram aesthetic}"
IMAGE_STACK_TEST_CHECKPOINT="${IMAGE_STACK_TEST_CHECKPOINT:-latest}"

mkdir -p \
  "$COMFY_DIR/models/diffusion_models" \
  "$COMFY_DIR/models/loras/nemoflix-amd" \
  "$COMFY_DIR/models/text_encoders" \
  "$COMFY_DIR/models/vae"

download_if_missing() {
    local url="$1"
    local dest="$2"
    if [ -s "$dest" ]; then
        echo "exists: $dest"
        return 0
    fi
    mkdir -p "$(dirname "$dest")"
    local auth_args=()
    if [ -n "${HF_TOKEN:-}" ]; then
        auth_args=(--header="Authorization: Bearer ${HF_TOKEN}")
    elif [ -n "${HUGGINGFACE_HUB_TOKEN:-}" ]; then
        auth_args=(--header="Authorization: Bearer ${HUGGINGFACE_HUB_TOKEN}")
    fi
    wget -q --show-progress "${auth_args[@]}" "$url" -O "$dest.tmp"
    test -s "$dest.tmp"
    mv "$dest.tmp" "$dest"
}

# Official Comfy FLUX.2 image stack.
# Source: Comfy workflow template `templates-all_in_one-image_edit_models.json`.
download_if_missing "$HF_BASE_FLUX2/diffusion_models/flux2_dev_fp8mixed.safetensors" "$COMFY_DIR/models/diffusion_models/flux2_dev_fp8mixed.safetensors"
download_if_missing "$HF_BASE_FLUX2/vae/flux2-vae.safetensors" "$COMFY_DIR/models/vae/flux2-vae.safetensors"
download_if_missing "$HF_BASE_FLUX2/text_encoders/mistral_3_small_flux2_bf16.safetensors" "$COMFY_DIR/models/text_encoders/mistral_3_small_flux2_bf16.safetensors"
download_if_missing "$HF_BASE_Z_IMAGE/text_encoders/qwen_3_4b.safetensors" "$COMFY_DIR/models/text_encoders/qwen_3_4b.safetensors"

# If a LoRA output directory is provided, make those training outputs visible to ComfyUI without copying GBs.
LORA_OUTPUT_DIR="${NEMOFLIX_LORA_OUTPUT_DIR:-}"
if [ -n "$LORA_OUTPUT_DIR" ] && [ -d "$LORA_OUTPUT_DIR" ]; then
    find "$LORA_OUTPUT_DIR" -maxdepth 1 -type f -name '*.safetensors' -print0 | while IFS= read -r -d '' lora; do
        ln -sf "$lora" "$COMFY_DIR/models/loras/nemoflix-amd/$(basename "$lora")"
    done
fi

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files comfyui.service >/dev/null 2>&1; then
    systemctl restart comfyui.service
fi

for i in {1..60}; do
    if curl -sS --max-time 5 "$COMFY_URL/system_stats" >/dev/null; then
        break
    fi
    echo "Waiting for ComfyUI API... ($i/60)"
    sleep 5
done

curl -sS --max-time 10 "$COMFY_URL/system_stats"
curl -sS --max-time 10 "$COMFY_URL/models/diffusion_models"
curl -sS --max-time 10 "$COMFY_URL/models/text_encoders"
curl -sS --max-time 10 "$COMFY_URL/models/vae"
curl -sS --max-time 10 "$COMFY_URL/models/loras"
curl -sS --max-time 10 "$NEMOFLIX_API_URL/api/health"

if [ "$RUN_IMAGE_STACK_TEST" = "1" ]; then
    curl -sS -X POST "$NEMOFLIX_API_URL/api/lora-training/generate" \
      -H "Content-Type: application/json" \
      -d "{\"checkpoint\":\"${IMAGE_STACK_TEST_CHECKPOINT}\",\"prompt\":\"${IMAGE_STACK_TEST_PROMPT}\",\"submit\":false}"
fi

echo "FLUX.2 image stack installed"
