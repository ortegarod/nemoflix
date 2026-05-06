#!/bin/bash
set -Eeuo pipefail
set -x

# Install Ostris AI Toolkit on a disposable AMD MI300X ROCm droplet.
# Run after scripts/startup-script.sh so ROCm/system basics are already present.
# This is intentionally idempotent: safe to rerun on a fresh or partially initialized box.

APT_GET="apt-get -o DPkg::Lock::Timeout=300"
TOOLKIT_DIR="${TOOLKIT_DIR:-/root/ai-toolkit}"
TOOLKIT_VENV="${TOOLKIT_VENV:-/root/ai-toolkit-venv}"
TRAINING_DIR="${TRAINING_DIR:-/root/nemoflix-training}"
ROCM_INDEX_PRIMARY="${ROCM_INDEX_PRIMARY:-https://download.pytorch.org/whl/rocm7.2}"
ROCM_INDEX_FALLBACK="${ROCM_INDEX_FALLBACK:-https://download.pytorch.org/whl/rocm7.0}"
AI_TOOLKIT_REF="${AI_TOOLKIT_REF:-main}"
# CLI training is the default. The UI pulls NodeSource apt repo + nodejs and can
# trigger service restart/deferred-restart behavior on cloud images; keep it opt-in.
INSTALL_UI_DEPS="${INSTALL_UI_DEPS:-0}"
PYTHON_BIN="$TOOLKIT_VENV/bin/python"
export DEBIAN_FRONTEND=noninteractive
# Do not let Ubuntu's needrestart apt hook bounce services while we are connected
# over SSH. The AMD images default to automatic restarts; list-only keeps the
# installer non-interactive without touching sshd/network services mid-run.
export NEEDRESTART_MODE=l

trap 'echo "ERROR: AI Toolkit install failed at line $LINENO"' ERR

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root on the AMD droplet."
  exit 1
fi

echo "=== Installing AI Toolkit prerequisites ==="
$APT_GET update -y
$APT_GET install -y git git-lfs python3-pip python3.12-venv python3-dev build-essential pkg-config curl wget ffmpeg libgl1 libglib2.0-0

git lfs install --system || true

if command -v /opt/rocm/bin/rocm-smi >/dev/null 2>&1; then
  echo "=== ROCm GPU check ==="
  /opt/rocm/bin/rocm-smi || true
fi

echo "=== Creating isolated AI Toolkit venv: $TOOLKIT_VENV ==="
if [ ! -d "$TOOLKIT_VENV" ]; then
  python3 -m venv "$TOOLKIT_VENV"
fi
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel

echo "=== Installing ROCm PyTorch into AI Toolkit venv ==="
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url "$ROCM_INDEX_PRIMARY" || \
"$PYTHON_BIN" -m pip install torch torchvision torchaudio --index-url "$ROCM_INDEX_FALLBACK"

"$PYTHON_BIN" - <<'PY'
import torch
print('torch', torch.__version__)
print('cuda api available', torch.cuda.is_available())
if torch.cuda.is_available():
    print('device', torch.cuda.get_device_name(0))
PY

echo "=== Cloning/updating Ostris AI Toolkit ==="
if [ ! -d "$TOOLKIT_DIR/.git" ]; then
  git clone https://github.com/ostris/ai-toolkit.git "$TOOLKIT_DIR"
fi
git -C "$TOOLKIT_DIR" fetch --depth 1 origin "$AI_TOOLKIT_REF"
git -C "$TOOLKIT_DIR" checkout FETCH_HEAD
git -C "$TOOLKIT_DIR" submodule update --init --recursive

echo "=== Installing AI Toolkit Python requirements ==="
# Keep the ROCm torch we installed above; do not allow requirements to swap in CUDA wheels.
"$PYTHON_BIN" -m pip install -r "$TOOLKIT_DIR/requirements.txt" --extra-index-url "$ROCM_INDEX_PRIMARY"
"$PYTHON_BIN" -m pip install --upgrade accelerate huggingface_hub hf_transfer

mkdir -p \
  "$TRAINING_DIR/datasets" \
  "$TRAINING_DIR/output" \
  "$TRAINING_DIR/samples" \
  "$TRAINING_DIR/config" \
  "$TOOLKIT_DIR/config"

# If this script is run from a cloned Nemoflix repo, seed our checked-in config templates
# into the disposable training workspace.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if compgen -G "$REPO_DIR/training/*.yaml" >/dev/null; then
  cp -f "$REPO_DIR"/training/*.yaml "$TRAINING_DIR/config/"
fi

cat > "$TRAINING_DIR/README.md" <<'EOF'
# Nemoflix AI Toolkit Training Workspace

Persistent-ish training layout for disposable AMD droplets.

## Paths

- AI Toolkit: `/root/ai-toolkit`
- Venv: `/root/ai-toolkit-venv`
- Datasets: `/root/nemoflix-training/datasets`
- Configs: `/root/nemoflix-training/config`
- Outputs/checkpoints: `/root/nemoflix-training/output`
- Sample control images: `/root/nemoflix-training/samples`

## Run a config

```bash
cd /root/ai-toolkit
/root/ai-toolkit-venv/bin/python run.py /root/nemoflix-training/config/<config>.yaml
```

## Hugging Face token

For gated models, create `/root/ai-toolkit/.env`:

```bash
HF_TOKEN=hf_xxx
HF_HUB_ENABLE_HF_TRANSFER=1
```

## Character dataset conventions

Image/FLUX LoRA:
- 20-40 good face/body images
- one `.txt` caption beside each image
- include trigger word, e.g. `character_trigger, person, portrait, natural lighting`

Wan I2V character LoRA:
- 10-30 short clips, ideally 3-8 seconds
- one `.txt` caption beside each clip
- include trigger word, e.g. `character_trigger, person, walking outdoors, close-up face`
- trim dead time; varied angles/lighting/backgrounds; avoid sunglasses
EOF

cat > "$TRAINING_DIR/run-ai-toolkit.sh" <<'EOF'
#!/bin/bash
set -Eeuo pipefail
CONFIG_PATH="${1:?Usage: /root/nemoflix-training/run-ai-toolkit.sh /root/nemoflix-training/config/job.yaml}"
cd /root/ai-toolkit
export HF_HUB_ENABLE_HF_TRANSFER="${HF_HUB_ENABLE_HF_TRANSFER:-1}"
exec /root/ai-toolkit-venv/bin/python run.py "$CONFIG_PATH"
EOF
chmod +x "$TRAINING_DIR/run-ai-toolkit.sh"

if [ "$INSTALL_UI_DEPS" = "1" ]; then
  if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)' 2>/dev/null; then
    echo "=== Installing Node.js 22 for optional AI Toolkit UI ==="
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    $APT_GET install -y nodejs
  fi
  if [ -f "$TOOLKIT_DIR/ui/package.json" ]; then
    echo "=== Installing AI Toolkit UI dependencies ==="
    (cd "$TOOLKIT_DIR/ui" && npm install)
  fi
fi

if [ "$INSTALL_UI_DEPS" = "1" ]; then
  cat > /etc/systemd/system/ai-toolkit-ui.service <<EOF
[Unit]
Description=Ostris AI Toolkit UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$TOOLKIT_DIR/ui
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="AI_TOOLKIT_AUTH=change-me"
ExecStart=/usr/bin/npm run build_and_start
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
fi

"$PYTHON_BIN" - <<'PY'
import importlib
mods = ['torch', 'accelerate', 'diffusers', 'transformers', 'huggingface_hub']
for name in mods:
    mod = importlib.import_module(name)
    print(name, getattr(mod, '__version__', 'ok'))
PY

echo "=== AI Toolkit install complete ==="
echo "Toolkit:  $TOOLKIT_DIR"
echo "Venv:     $TOOLKIT_VENV"
echo "Training: $TRAINING_DIR"
echo "Run CLI:  $TRAINING_DIR/run-ai-toolkit.sh /root/nemoflix-training/config/job.yaml"
echo "UI:       optional; rerun with INSTALL_UI_DEPS=1, then set AI_TOOLKIT_AUTH before starting ai-toolkit-ui.service"
