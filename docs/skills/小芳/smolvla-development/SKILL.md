---
name: smolvla-development
description: Train, download, and run inference with SmolVLA robot policies — includes China-network workarounds, MPS GPU, venv setup, and common pitfalls
platforms: [macos, linux]
---

# SmolVLA Development

Use this skill when working with SmolVLA policies (training, downloading pretrained models, inference) in the `lerobot-smolvla-lew` project. Covers dependency installation in China, model caching, MPS GPU caveats, and common crash fixes.

## Quick Start

```bash
cd ~/lerobot-smolvla-lew

# 1. Ensure Python 3.12 venv (NOT system Python 3.9!)
.venv/bin/python3.12 --version   # Must be 3.12+

# 2. Install deps (China mirror)
.venv/bin/pip3.12 install torch huggingface_hub datasets draccus accelerate \
  einops transformers Pillow gymnasium torchvision wandb av \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn

# 3. Install project in dev mode
PYTHONPATH=src .venv/bin/pip3.12 install -e . --no-deps

# 4. Run training (synthetic data, pure local)
.venv/bin/python3.12 train_mini_v2.py

# 5. Download pretrained model + run inference
HF_ENDPOINT=https://hf-mirror.com .venv/bin/python3.12 infer_smolvla.py
```

## Environment Setup (China)

### pip mirror
**Always** use Tsinghua mirror for pip in China:
```
-i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
```

### HuggingFace Hub mirror
Set `HF_ENDPOINT=https://hf-mirror.com` before any HF download:
```python
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
```

### Python version: must be 3.12+
The project uses `str | torch.device` union syntax (PEP 604). System Python 3.9 will crash with `TypeError: unsupported operand type(s) for |`. Use the project venv at `.venv/bin/python3.12`.

### Model download: large-file strategy
HF `snapshot_download` often times out on files >500MB. For large safetensors files, use `curl` with resume support:

```bash
curl -L -C - --connect-timeout 30 --max-time 600 \
  "https://hf-mirror.com/HuggingFaceTB/SmolVLM2-500M-Video-Instruct/resolve/main/model.safetensors" \
  -o "$CACHE_PATH/model.safetensors"
```

Key flags:
- `-C -`: resume partial download
- `--max-time 600`: 10-minute timeout (re-run with `-C -` to continue)
- `--connect-timeout 30`: 30s initial connect timeout

Expected sizes: SmolVLM2 backbone ~1.9GB, SmolVLA policy ~865MB.

## Model Architecture

### lerobot/smolvla_base (official, 450M params)
```
SmolVLM2-500M-Video-Instruct (frozen VLM backbone)
  → SmolVLMWithExpertModel (16 VLM layers + expert layers)
  → DiT Flow-Matching Action Head
  → 7-DOF action output
```

Config keys:
- `smolvlm_name`: "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
- `freeze_smolvlm`: True (inference), True/False (training)
- `action_model_type`: "DiT-B"
- `action_hidden_size`: 512
- `action_num_layers`: 2

### SmolVLA-LEW (custom, 263K params, self-trained)
Pure CNN encoder + DiT action head. No external downloads. See `train_mini_v2.py`.

## Inference

### Loading pretrained model (6-8 seconds on M1)
```python
from lerobot.policies.smolvla import SmolVLAPolicy
policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base", local_files_only=True)
policy.eval()
```

### Inference batch format
The model REQUIRES language tokens even if unused:
```python
batch = {
    "observation.image": torch.randn(1, 3, 64, 64),    # RGB image
    "observation.state": torch.randn(1, state_dim),     # Robot state
    "observation.language.tokens": torch.zeros(1, 64, dtype=torch.long),
    "observation.language.attention_mask": torch.zeros(1, 64, dtype=torch.bool),
}
action = policy.select_action(batch)  # NOT .predict()!
```

### Critical pitfalls (inference)
1. **Method name**: use `select_action()`, NOT `predict()` — the latter doesn't exist
2. **Device alignment**: ALL tensors must be on the same device as the model
   ```python
   DEV = next(policy.parameters()).device
   batch = {k: v.to(DEV) for k, v in batch.items()}
   ```
3. **attention_mask dtype**: MUST be `torch.bool`, NOT `torch.long`. Long tensors cause `RuntimeError: where expected condition to be a boolean tensor`
4. **Language tokens required**: both `observation.language.tokens` AND `observation.language.attention_mask`
5. **Missing num2words**: `pip install num2words` (needed by SmolVLM processor)

### Loading time expectations (M1 MPS)
- Model loading: 6-8 seconds (489 weight chunks)
- Single inference: ~1.7 seconds
- Loading outputs "Reducing the number of VLM layers to 16" — this is normal

## Training

### Minimal self-training (no downloads)
`train_mini_v2.py` — 263K params, CNN+DiT, synthetic data, 18 seconds:
```bash
.venv/bin/python3.12 train_mini_v2.py
```

Configurable: `EPOCHS`, `BS`, `LR`, `N` at top of file.

### Full SmolVLA training (requires dataset)
```bash
PYTHONPATH=src .venv/bin/lerobot-train --config config_smolvla_mini.yaml
```
Datasets available locally: `lerobot/pusht`, `lerobot/metaworld_mt50` (if downloaded).

## Common Fixes

### PyAV v18: `module 'av' has no attribute 'option'`
PyAV 18 removed `av.option.Option`. Fix in `src/lerobot/datasets/pyav_utils.py`:
- `_get_codec_options_by_name`: try `codec.descriptor.options` first, fall back to `codec.options`
- `_check_option_value`: change type hint from `av.option.Option` to `Any`

### Z-MAX GUI: `PluggingSceneModule` not defined
The `studio.py` at `tools/gui/studio.py` has a broken PluginScene class. Comment out the corrupted section (around line 6154) and the `self.stack.addWidget(PluggingSceneModule())` call (line 6562). Install PyQt5: `pip install PyQt5 PyQt5-sip`.

### Z-MAX GUI: `grpc` not found
`pip install grpcio grpcio-tools`

### MPS device mismatch
When tensors are on CPU but model is on MPS: create all tensors on the model's device. Use `next(policy.parameters()).device` to detect.

## Project Files

| File | Purpose |
|------|---------|
| `train_mini_v2.py` | Minimal self-training (CNN+DiT, no downloads) |
| `train_synth.py` | SmolVLA-LEW training with synthetic data |
| `infer_smolvla.py` | Download + inference pretrained SmolVLA |
| `config_smolvla_mini.yaml` | Training config for lerobot-train CLI |
| `tools/gui/studio.py` | Z-MAX Studio GUI (PyQt5) |
| `src/lerobot/policies/smolvla/` | Original SmolVLA policy |
| `src/lerobot/policies/smolvla_lew/` | Custom SmolVLA-LEW policy |
