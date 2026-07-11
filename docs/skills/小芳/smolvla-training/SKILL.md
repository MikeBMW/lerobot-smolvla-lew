---
name: smolvla-training
description: Train and run inference with SmolVLA robot policies (lerobot/smolvla_base) — download, MPS GPU, debugging
platforms: [macos, linux]
---

# SmolVLA Training & Inference

End-to-end workflow for downloading, training, and running inference with SmolVLA robot learning models from the LeRobot framework. Covers the `lerobot/smolvla_base` pre-trained model (450M params, SmolVLM2-500M backbone + DiT Flow-Matching action head) as well as self-training with smaller architectures.

## Quick Reference

| What | Command / Path |
|------|---------------|
| Project | `~/lerobot-smolvla-lew` |
| Python | `.venv/bin/python3` (3.12+) |
| Pre-trained model | `lerobot/smolvla_base` (450M) |
| Self-trained model | `outputs/train/smolvla_lew_mini/model.pt` (263K) |
| Training script | `train_mini_v2.py` |
| Inference script | `infer_smolvla.py` |

## Model Architecture

```
SmolVLA = SmolVLM2-500M-Video-Instruct (frozen)
        + Expert layers (learnable VLM subset)
        + DiT Flow-Matching Action Head
```

- **Backbone**: HuggingFaceTB/SmolVLM2-500M-Video-Instruct (~1.9 GB safetensors)
- **Policy weights**: lerobot/smolvla_base (~865 MB safetensors)
- **Total loaded**: ~450M parameters
- **Input**: image (3×H×W), state vector, language tokens + attention mask
- **Output**: action vector (dimension depends on dataset)

## Prerequisites

### Python Version

**Must use Python 3.12+**. System Python 3.9 fails with `TypeError: unsupported operand type(s) for |` due to PEP 604 union type syntax used throughout LeRobot.

```bash
# Activate the project venv
cd ~/lerobot-smolvla-lew
.venv/bin/python3 --version  # Should be 3.12.x
```

### Dependencies

Install with Tsinghua mirror (fast in China):

```bash
.venv/bin/pip3 install torch torchvision huggingface_hub datasets draccus \
  accelerate einops transformers Pillow gymnasium wandb av termcolor \
  num2words -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn

# Install LeRobot itself
.venv/bin/pip3 install -e . --no-deps
```

### Critical dependency: num2words

The SmolVLM processor requires `num2words`. Without it, loading fails with:
`ImportError: Package num2words is required to run SmolVLM processor.`

## Model Download

### Problem: HuggingFace Hub is slow/timeout in China

Default HF Hub connections timeout for files >100MB. The SmolVLM2 backbone alone is 1.9 GB.

### Solution: Use hf-mirror.com

```python
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
```

For large files that still time out with snapshot_download, use `curl` directly:

```bash
# Download model.safetensors in chunks with resume support
curl -L -C - --connect-timeout 30 --max-time 900 \
  "https://hf-mirror.com/HuggingFaceTB/SmolVLM2-500M-Video-Instruct/resolve/main/model.safetensors" \
  -o "$CACHE_DIR/model.safetensors"
```

Each `--max-time 900` run downloads ~1 GB on typical connections. Use `-C -` to resume.

### After Download: File Placement

The downloaded model file must be placed in the correct HuggingFace cache snapshot directory:

```bash
# Find the snapshot dir
SNAPSHOT=$(ls -d ~/.cache/huggingface/hub/models--REPO--NAME/snapshots/*/ | head -1)
cp downloaded_model.safetensors "$SNAPSHOT/"
```

## Inference

### Loading the Pre-trained Model

```python
from lerobot.policies.smolvla import SmolVLAPolicy

# Offline load (no network)
policy = SmolVLAPolicy.from_pretrained(
    'lerobot/smolvla_base',
    local_files_only=True
)
```

Loading takes ~8 seconds on M1 (1.9 GB safetensors → 450M params in memory).

### Running Inference

**CRITICAL**: The model requires these batch keys:

| Key | Shape | Type | Description |
|-----|-------|------|-------------|
| `observation.image` | `[B, 3, H, W]` | float32 | RGB image |
| `observation.state` | `[B, state_dim]` | float32 | Robot state vector |
| `observation.language.tokens` | `[B, seq_len]` | int64 | Language token IDs |
| `observation.language.attention_mask` | `[B, seq_len]` | **bool** | Must be bool, NOT long! |

```python
import torch

# Get device from model
DEV = next(policy.parameters()).device

# Build batch (ALL tensors must be on same device as model!)
batch = {}
for name, feat in policy.config.input_features.items():
    batch[name] = torch.randn(1, *feat.shape, device=DEV)

# Language tokens (required even for non-language tasks)
batch['observation.language.tokens'] = torch.zeros(1, 64, dtype=torch.long, device=DEV)
batch['observation.language.attention_mask'] = torch.zeros(1, 64, dtype=torch.bool, device=DEV)  # BOOL!

# Inference
with torch.no_grad():
    action = policy.select_action(batch)  # NOT .predict()!
```

### Common Pitfalls

1. **`.predict()` does not exist** — use `policy.select_action(batch)`
2. **`KeyError: 'observation.language.tokens'`** — language tokens are always required
3. **`KeyError: 'observation.language.attention_mask'`** — attention mask is always required
4. **`RuntimeError: where expected condition to be a boolean tensor`** — attention mask must be `dtype=torch.bool`, NOT `long`
5. **`RuntimeError: input(device='cpu') and weight(device=mps:0') must be on same device`** — ALL input tensors must be on the model's device. Use `device=DEV` when creating tensors.

Inference speed: ~1.7 seconds per forward pass on M1 MPS.

## Self-Training (Mini Model)

When real datasets are unavailable or network is slow, train on synthetic data:

```bash
cd ~/lerobot-smolvla-lew
.venv/bin/python3 train_mini_v2.py
```

### Architecture (263K params, 18-second training)

```
Image (3×64×64) → TinyCNN (4 conv layers) → 256-dim feature
State (2-dim) ──────────────────────────────┘
                                              ↓ concat
Time step (1-dim) ───────────────────────────┘
                                              ↓
                              DiT MLP (259→256→256→2) → Action
```

Training: Flow Matching (regress velocity field between noise and action).
Inference: 4-step ODE integration to denoise.

Results: Loss 0.94→0.51 (↓46%) on 50 epochs, 200 samples, batch=4.

### Limitations of Synthetic Data

The model learns the random mapping well (loss drops) but prediction accuracy is poor because synthetic data has no underlying structure. For usable models, real datasets (pusht, metaworld_mt50) are needed.

## PyAV Compatibility

LeRobot uses PyAV for video decoding. PyAV v18+ removed `av.option.Option`. If you see:

```
AttributeError: module 'av' has no attribute 'option'
```

The fix is in `src/lerobot/datasets/pyav_utils.py` — replace `av.option.Option` with `Any` and add a fallback for the options dictionary.

## Offline Mode

Use `HF_HUB_OFFLINE=1` to prevent any network calls during model loading:

```bash
HF_HUB_OFFLINE=1 .venv/bin/python3 infer_smolvla.py
```

Or in Python:
```python
os.environ["HF_HUB_OFFLINE"] = "1"
policy = SmolVLAPolicy.from_pretrained('lerobot/smolvla_base', local_files_only=True)
```
