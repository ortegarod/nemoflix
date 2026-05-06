#!/bin/bash
set -Eeuo pipefail
set -x
exec > >(tee -a /var/log/setup.log) 2>&1

trap 'echo "ERROR: setup failed at line $LINENO"' ERR

APT_GET="apt-get -o DPkg::Lock::Timeout=300"
PYTHON_BIN="/root/comfyui-venv/bin/python"
APP_REPO_URL="https://github.com/ortegarod/nemoflix.git"
APP_DIR="/root/nemoflix"

echo "=== AMD MI300X ROCm 7.2 ComfyUI Setup Starting ==="

# Refresh package metadata before installing dependencies.
$APT_GET update -y

# Git is required to clone ComfyUI and ComfyUI-Manager.
$APT_GET install -y git

# Python tooling for an isolated host virtual environment.
$APT_GET install -y python3-pip
$APT_GET install -y python3.12-venv

# wget is required by optional stack install scripts.
$APT_GET install -y wget

# htop is optional, but useful for manual droplet debugging.
$APT_GET install -y htop

# curl is useful for local API health checks.
$APT_GET install -y curl

# Verify host GPU and ROCm visibility.
echo "=== Host GPU Check ==="
/opt/rocm/bin/rocm-smi
/opt/rocm/bin/rocminfo > /tmp/rocminfo.txt
head -20 /tmp/rocminfo.txt

# Create virtual environment on the host.
echo "=== Creating Python venv ==="
python3 -m venv /root/comfyui-venv
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel

# Install PyTorch for ROCm inside venv.
# This is the slower path, but it is explicit and avoids DigitalOcean's Jupyter/Docker appliance behavior.
echo "=== Installing PyTorch for ROCm ==="
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.2 || \
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm7.0 || \
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

# Verify PyTorch sees the GPU.
echo "=== PyTorch GPU Check ==="
"$PYTHON_BIN" -c "import torch; print('PyTorch:', torch.__version__); print('ROCm available:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None')"

# Clone the project repo. This is the application layer that owns the agent-native API wrapper.
echo "=== Cloning Nemoflix repo ==="
git clone --depth 1 "$APP_REPO_URL" "$APP_DIR"

# Install the agent-native API wrapper. This service talks to ComfyUI's native
# HTTP API and keeps humans out of the ComfyUI browser UI.
if [ -f "$APP_DIR/requirements.txt" ]; then
    "$PYTHON_BIN" -m pip install -r "$APP_DIR/requirements.txt"
fi

# Install ComfyUI.
echo "=== Installing ComfyUI ==="
cd /root
git clone https://github.com/comfyanonymous/ComfyUI.git

# Install ComfyUI-Manager.
git clone https://github.com/ltdrdata/ComfyUI-Manager.git /root/ComfyUI/custom_nodes/ComfyUI-Manager
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
systemctl start comfyui.service

# Create a small product/API layer over ComfyUI's execution API.
cat > /etc/systemd/system/nemoflix-amd-api.service << EOF
[Unit]
Description=Nemoflix AMD Agent API
After=network-online.target comfyui.service
Wants=network-online.target comfyui.service

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
Environment="PATH=/root/comfyui-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="PYTHONPATH=$APP_DIR/app"
Environment="COMFY_URL=http://127.0.0.1:8188"
ExecStart=$PYTHON_BIN -m uvicorn nemoflix_amd.api:app --host 0.0.0.0 --port 8190
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable nemoflix-amd-api.service
systemctl start nemoflix-amd-api.service

# Show service status in log.
systemctl --no-pager --full status comfyui.service
systemctl --no-pager --full status nemoflix-amd-api.service

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
curl -sS --max-time 5 http://127.0.0.1:8190/api/health

echo "=== Setup Complete ==="
echo "Install Wan 2.2 video stack: $APP_DIR/scripts/install-video-stack.sh"
echo "Install AI Toolkit training stack: $APP_DIR/scripts/install-ai-toolkit.sh"
