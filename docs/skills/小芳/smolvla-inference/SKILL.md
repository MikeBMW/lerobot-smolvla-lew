---
name: smolvla-inference
description: Download, load, and run SmolVLA pretrained models for robot action prediction — offline cache, MPS acceleration, real-time Gateway integration
platforms: [macos, linux]
---

# SmolVLA Inference

Download pretrained SmolVLA models and run inference for robot action prediction. Supports offline caching (no repeated downloads), MPS acceleration on Apple Silicon, and real-time integration with the Hermes Gateway API for live robot data.

## Model Overview

- **Official model**: `lerobot/smolvla_base` (397 likes, 49K downloads on HuggingFace)
- **Backbone**: SmolVLM2-500M-Video-Instruct (500M params)
- **Action head**: DiT Flow-Matching (6-DOF action prediction)
- **Total params**: ~450M
- **Disk size**: 865 MB (policy) + 1,935 MB (VLM backbone) = ~2.8 GB

## Download

### Via hf-mirror (required in China)

HuggingFace Hub is slow/unreachable from within China. Always use the mirror:

```bash
HF_ENDPOINT=https://hf-mirror.com
```

### Two-stage download

The model has two components. The VLM backbone is the bottleneck (1.9GB).

```bash
cd ~/lerobot-smolvla-lew

# Stage 1: Policy weights (865 MB) — use curl with resume
HF_SNAP=~/.cache/huggingface/hub/models--lerobot--smolvla_base/snapshots
mkdir -p "$HF_SNAP"
curl -L -C - --connect-timeout 30 --max-time 600 \
  "https://hf-mirror.com/lerobot/smolvla_base/resolve/main/model.safetensors" \
  -o "$HF_SNAP/model.safetensors"

# Stage 2: VLM backbone (1,935 MB) — same pattern, different path
VLM_SNAP=~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/7b375e1b...
curl -L -C - --connect-timeout 30 --max-time 600 \
  "https://hf-mirror.com/HuggingFaceTB/SmolVLM2-500M-Video-Instruct/resolve/main/model.safetensors" \
  -o "$VLM_SNAP/model.safetensors"

# Stage 3: Config files (fast, use snapshot_download)
HF_ENDPOINT=https://hf-mirror.com python3 -c "
from huggingface_hub import snapshot_download
# Policy configs
snapshot_download('lerobot/smolvla_base', allow_patterns=['config.json','*.json','*.md'], ignore_patterns=['*.safetensors'])
# VLM configs
snapshot_download('HuggingFaceTB/SmolVLM2-500M-Video-Instruct', allow_patterns=['config.json','preprocessor*','tokenizer*','*.md','*.json'], ignore_patterns=['*.safetensors'])
"
```

**Important**: curl has a `--max-time` limit. Downloads may time out at ~600-900 seconds. Use `-C -` (resume) to continue from where it left off. Multiple resume attempts are expected.

### Check cache

```bash
find ~/.cache/huggingface/hub -name "model.safetensors" -exec ls -lh {} \;
```

### Dependencies

```bash
pip3 install num2words  # Required by SmolVLM processor
```

## Loading

### Always use local_files_only after download

```python
from lerobot.policies.smolvla import SmolVLAPolicy

# Load from cache (offline, fast)
policy = SmolVLAPolicy.from_pretrained(
    'lerobot/smolvla_base',
    local_files_only=True
)
```

### Loading time

- **With cached weights (local_files_only=True)**: ~6-8 seconds
- **With HF hub check**: 30+ seconds (timeout-prone in China)
- **Always use** `local_files_only=True` after the initial download

### Device

- Model loads on the device specified in config, then auto-detects available hardware
- On Apple Silicon (M1/M2): auto-switches to MPS (Metal Performance Shaders)
- MPS inference is 1.7 seconds per prediction

## Inference API

### Key method: `select_action(batch)`

The SmolVLA policy uses `select_action()`, not `predict()` or `forward()`.

### Required batch fields

The model requires specific fields in the input dictionary. Extract them from the config:

```python
cfg = policy.config
batch = {}

# Required input features (from config.input_features)
for name, feat in cfg.input_features.items():
    shape = list(feat.shape)
    if feat.type.value == "VISUAL":
        batch[name] = torch.randn(1, *shape)  # Placeholder image
    elif feat.type.value == "STATE":
        batch[name] = torch.randn(1, *shape)  # Robot state vector
    else:
        batch[name] = torch.randn(1, *shape)

# Language tokens (ALWAYS required regardless of config)
batch["observation.language.tokens"] = torch.zeros(1, 64, dtype=torch.long)
batch["observation.language.attention_mask"] = torch.zeros(1, 64, dtype=torch.bool)
```

**Pitfall**: The language tokens are NOT listed in `input_features` but are REQUIRED by `select_action()`. Omitting them causes `KeyError: 'observation.language.tokens'`.

### Run inference

```python
with torch.no_grad():
    action = policy.select_action(batch)
# action.shape: (1, action_dim) — 6 values for XMS5-R800
```

### Real-time loop pattern

```python
import time, urllib.request, json

while True:
    # 1. Get current state from Gateway API
    with urllib.request.urlopen("http://localhost:8080/joints") as r:
        data = json.loads(r.read())
    joints = data["joints"]
    
    # 2. Update batch with current joint positions
    positions = torch.tensor(list(joints.values()), dtype=torch.float32)
    batch["observation.state"] = positions.unsqueeze(0)
    
    # 3. Predict
    with torch.no_grad():
        action = policy.select_action(batch)
    
    print(f"Action: {action[0].tolist()}")
    time.sleep(1.0)
```

## MPS Pitfalls

### Device mismatch errors

When using MPS (Apple Silicon), ALL tensors must be on the same device:

```python
DEV = next(policy.parameters()).device  # Get model's device
# Always create tensors on this device:
tensor = torch.randn(1, 64, device=DEV)
```

Common error: `RuntimeError: input(device='cpu') and weight(device='mps:0') must be on the same device`

### Slow first load on MPS

The first model load on MPS takes ~6-8 seconds (weight initialization). Subsequent loads from cache are faster.

## Training (from scratch)

For training your own SmolVLA model, see `train_mini_v2.py` in the project root. It implements a compact CNN + DiT Flow-Matching architecture that trains in 18 seconds on MPS with synthetic data (263K params, no external downloads needed). Use this for quick experimentation before scaling to full SmolVLM2 backbone.

## Project Files

| File | Purpose |
|------|---------|
| `infer_smolvla.py` | Standalone inference with random inputs |
| `infer_realtime.py` | Real-time inference loop via Gateway API |
| `train_mini_v2.py` | Compact training script (CNN+DiT, synthetic data) |
| `train_synth.py` | Attempts full SmolVLALewPolicy training |

## Relevant Skills

- `hermes-gateway-robot` — Gateway setup, Orin connection, data streaming
- `orin-ssh-persistence` — SSH key persistence on Orin
- `orin-simulator` — Offline simulation when Orin is unreachable
