#!/bin/bash
set -Eeuo pipefail
set -x
exec > >(tee -a /var/log/setup.log) 2>&1

trap 'echo "ERROR: setup failed at line $LINENO"' ERR

APT_GET="apt-get -o DPkg::Lock::Timeout=300"
PYTHON_BIN="/root/comfyui-venv/bin/python"
APP_REPO_URL="${APP_REPO_URL:-https://github.com/ortegarod/nemoflix.git}"
APP_DIR="${APP_DIR:-/root/nemoflix}"
NEMOFLIX_OUTPUT_DIR="${NEMOFLIX_OUTPUT_DIR:-/root/ComfyUI/output}"
COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"

export DEBIAN_FRONTEND=noninteractive
# DigitalOcean/Ubuntu images can auto-restart services during apt operations.
# Keep restarts list-only so SSH/network services do not bounce mid-bootstrap.
export NEEDRESTART_MODE=l

echo "=== AMD MI300X ROCm 7.2 ComfyUI Worker Setup Starting ==="

# Refresh package metadata before installing dependencies.
$APT_GET update -y

# Base utilities and Python tooling.
$APT_GET install -y git git-lfs python3-pip python3.12-venv wget htop curl ca-certificates

git lfs install --system || true

# Verify host GPU and ROCm visibility.
echo "=== Host GPU Check ==="
/opt/rocm/bin/rocm-smi
/opt/rocm/bin/rocminfo > /tmp/rocminfo.txt
head -20 /tmp/rocminfo.txt

# Create virtual environment on the host.
echo "=== Creating Python venv ==="
if [ ! -d /root/comfyui-venv ]; then
    python3 -m venv /root/comfyui-venv
fi
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel

# Install PyTorch for ROCm inside venv.
# This is explicit and avoids DigitalOcean's Jupyter/Docker appliance behavior.
echo "=== Installing PyTorch for ROCm ==="
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.2 || \
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.0 || \
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

# Verify PyTorch sees the GPU.
echo "=== PyTorch GPU Check ==="
"$PYTHON_BIN" -c "import torch; print('PyTorch:', torch.__version__); print('ROCm available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"

# Clone or update the project repo. The droplet uses this repo only for worker
# install scripts/workflow assets. The durable API, database, Studio UI, and
# control plane live on the VPS.
echo "=== Cloning/updating Nemoflix repo ==="
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" fetch --depth 1 origin main
    git -C "$APP_DIR" reset --hard origin/main
else
    git clone --depth 1 "$APP_REPO_URL" "$APP_DIR"
fi

# NOTE: Studio frontend and Nemoflix AMD API are hosted on the VPS, not on the
# droplet. This droplet is disposable and runs ComfyUI only.

# Install ComfyUI.
echo "=== Installing ComfyUI ==="
cd /root
if [ ! -d /root/ComfyUI/.git ]; then
    git clone https://github.com/comfyanonymous/ComfyUI.git
else
    git -C /root/ComfyUI pull --ff-only || true
fi

# Install ComfyUI-Manager.
if [ ! -d /root/ComfyUI/custom_nodes/ComfyUI-Manager/.git ]; then
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git /root/ComfyUI/custom_nodes/ComfyUI-Manager
fi
cd /root/ComfyUI

# Install ComfyUI requirements inside venv.
"$PYTHON_BIN" -m pip install -r requirements.txt
"$PYTHON_BIN" -m pip install -r /root/ComfyUI/custom_nodes/ComfyUI-Manager/requirements.txt

# Copy official example for testing.
cp /root/ComfyUI/script_examples/basic_api_example.py /root/test_comfyui.py

# Create ComfyUI systemd service on the host.
cat > /etc/systemd/system/comfyui.service << EOF
[Unit]
Description=ComfyUI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/ComfyUI
Environment="PATH=/root/comfyui-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$PYTHON_BIN /root/ComfyUI/main.py --listen 0.0.0.0 --port 8188
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable comfyui.service
systemctl restart comfyui.service

systemctl daemon-reload

# Show service status in log.
systemctl --no-pager --full status comfyui.service

# Verify API from the host.
echo "=== Waiting for ComfyUI API ==="
for i in {1..60}; do
    if curl -sS --max-time 5 http://127.0.0.1:8188/system_stats; then
        break
    fi
    echo "Waiting for ComfyUI API... ($i/60)"
    sleep 5
done
curl -sS --max-time 5 http://127.0.0.1:8188/system_stats

# Install model stacks.
echo "=== Installing FLUX.2 image stack ==="
bash "$APP_DIR/scripts/install-image-stack.sh"

echo "=== Installing Wan 2.2 video stack ==="
bash "$APP_DIR/scripts/install-video-stack.sh"

echo "=== Setup Complete ==="
echo "ComfyUI worker: http://<droplet-ip>:8188"
echo "Studio UI and Nemoflix AMD API are hosted on the VPS."
echo "On the VPS, set COMFY_URL=http://<droplet-ip>:8188 in nemoflix-amd-api.service and restart it."
echo ""
echo "!!! REMINDER !!! Transfer the LoRA model to the droplet (and dataset if traning a LoRA):"
echo "  scp -i ~/.ssh/id_ed25519_amd_hackathon /home/ubuntu/nemoflix-amd-backups/2026-05-06-rigo-flux2/loras/rigo_flux2_lora_v1_dop.safetensors root@<droplet-ip>:/root/ComfyUI/models/loras/nemoflix-amd/"
echo "Then restart ComfyUI: systemctl restart comfyui.service"
