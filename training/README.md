# Nemoflix AMD Training

Scripts/config templates for disposable AMD MI300X droplets.

## Install AI Toolkit on the droplet

After `scripts/startup-script.sh` finishes on a fresh droplet:

```bash
cd /root/nemoflix
bash scripts/install-ai-toolkit.sh
```

The installer creates:

- `/root/ai-toolkit` — Ostris AI Toolkit checkout
- `/root/ai-toolkit-venv` — isolated ROCm Python venv
- `/root/nemoflix-training` — datasets/configs/output workspace
- `/root/nemoflix-training/run-ai-toolkit.sh` — CLI runner

## Train

Copy a config into `/root/nemoflix-training/config/`, put media in `/root/nemoflix-training/datasets/...`, then:

```bash
/root/nemoflix-training/run-ai-toolkit.sh /root/nemoflix-training/config/<job>.yaml
```

## Optional UI

The installer creates but does not start:

```bash
ai-toolkit-ui.service
```

Before exposing it, set a real `AI_TOOLKIT_AUTH` value in the service or an override.
