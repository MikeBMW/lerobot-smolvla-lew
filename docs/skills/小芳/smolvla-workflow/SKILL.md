---
name: smolvla-workflow
description: Download, train, and run inference with SmolVLA robot policy models on Apple Silicon
platforms: [macos]
---

# SmolVLA Model Workflow

End-to-end workflow for SmolVLA vision-language-action models: download pretrained models, train from scratch, and run inference. Optimized for Apple Silicon (MPS).

## Architecture

SmolVLA = **SmolVLM2-500M-Video-Instruct** (frozen VLM backbone) + **DiT Flow-Matching Action Head**.

- VLM backbone: `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` (~1.9 GB)
- Pretrained policy: `lerobot/smolvla_base` (~865 MB policy weights + 1.9 GB backbone = ~2.8 GB total)
- Total params: **450,046,176** (VLM frozen, only action head trained)

## Project Setup

```bash
cd ~/lerobot-smolvla-lew
# Python 3.12 venv with all deps
.venv/bin/pip3 list  # check installed
```

Key dependencies: `torch`, `transformers`, `datasets`, `draccus`, `accelerate`, `huggingface_hub`, `gymnasium`, `Pillow`, `num2words`, `grpcio`, `av`

## Downloading Models (China / slow network)

HuggingFace is slow in China. Use **hf-mirror.com**:

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

### Download pretrained model (2 parts)

**Part 1: Backbone (SmolVLM2-500M, ~1.9 GB)**
```bash
DEST=~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/7b375e1b73b11138ff12fe22c8f2822d8fe03467
curl -L -C - --max-time 1200 \
  "https://hf-mirror.com/HuggingFaceTB/SmolVLM2-500M-Video-Instruct/resolve/main/model.safetensors" \
  -o "$DEST/model.safetensors"
```
Uses `-C -` for resume support. The 900s timeout in curl will need restarting for files >900MB.

**Part 2: Policy weights (lerobot/smolvla_base, ~865 MB)**
```bash
DEST=~/.cache/huggingface/hub/models--lerobot--smolvla_base/snapshots
curl -L -C - --max-time 600 \
  "https://hf-mirror.com/lerobot/smolvla_base/resolve/main/model.safetensors" \
  -o "$DEST/model.safetensors"
```

**Part 3: Config files (fast)**
```python
from huggingface_hub import snapshot_download
snapshot_download('lerobot/smolvla_base', allow_patterns=['config.json','*.json'], ignore_patterns=['*.safetensors'])
snapshot_download('HuggingFaceTB/SmolVLM2-500M-Video-Instruct', allow_patterns=['*.json','tokenizer*','*.md'], ignore_patterns=['*.safetensors'])
```

## Model Verification

After download, verify all files are in the correct HF snapshot directories:
```bash
ls ~/.cache/huggingface/hub/models--lerobot--smolvla_base/snapshots/*/
ls ~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/snapshots/*/
```

## Inference

```python
from lerobot.policies.smolvla import SmolVLAPolicy
import torch

# Load pretrained (offline mode to avoid network)
policy = SmolVLAPolicy.from_pretrained('lerobot/smolvla_base', local_files_only=True)
policy.eval()
DEV = next(policy.parameters()).device  # mps:0 on M1

# Prepare batch with ALL required fields
cfg = policy.config
batch = {}
for name, feat in cfg.input_features.items():
    batch[name] = torch.randn(1, *feat.shape, device=DEV)
batch['observation.language.tokens'] = torch.zeros(1, 64, dtype=torch.long, device=DEV)
batch['observation.language.attention_mask'] = torch.zeros(1, 64, dtype=torch.bool, device=DEV)

# Run
with torch.no_grad():
    action = policy.select_action(batch)  # ← select_action, NOT predict or forward
```

### Inference pitfalls
- Use **`select_action()`** for inference (not `predict` or `forward`)
- `observation.language.attention_mask` must be **bool** dtype, not long
- All tensors must be on the same device as the model
- Loading takes ~8 seconds on M1 (489 weight blocks)

## Training from Scratch

For quick training without downloading VLM backbone, use `train_mini_v2.py`:

```bash
cd ~/lerobot-smolvla-lew
.venv/bin/python3 train_mini_v2.py
```

This trains a **263K param** CNN + DiT model in **18 seconds** on MPS:
- TinyCNN encoder (3×64×64 → 256-dim)
- DiT Flow-Matching action head
- Synthetic data (200 samples)
- Loss: 0.94 → 0.51 in 50 epochs

Output: `outputs/train/smolvla_lew_mini/model.pt`

## PyAV Compatibility

PyAV v18 removed `av.option.Option`. Fix in `src/lerobot/datasets/pyav_utils.py`:
- Replace `av.option.Option` type hints with `Any`
- Wrap `codec.descriptor.options` access in try/except for PyAV >=18

## Device Handling

On Apple Silicon, the model auto-detects `mps` (Metal Performance Shaders). The config warns about 'cuda' not available — this is fine and the fallback to MPS works.

## Offline Simulation

When Orin or ROS2 is unavailable, use the WebSocket-based simulation Client-Server system for model validation. See `references/simulation-architecture.md` for the full protocol, sensor simulators, startup commands, and performance benchmarks.
