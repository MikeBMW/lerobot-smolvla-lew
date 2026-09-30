---
name: robotics-model-training
description: Train SmolVLA and other robot policies on Mac M1 — dependency setup, HF mirror, synthetic data, MPS GPU, and the full training pipeline
platforms: [macos]
---

# Robotics Model Training

Use this skill when training robot policies (SmolVLA, ACT, Diffusion Policy, etc.) on a Mac M1/M2/M3. Covers environment setup, dependency installation in China, data handling, MPS GPU training, and model saving.

## Project Context

The SmolVLA-LEW policy lives in `~/lerobot-smolvla-lew/src/lerobot/policies/smolvla_lew/`. Training scripts are at the repo root. The `.venv` at the repo root (Python 3.12) is the canonical environment.

## Environment Setup

### Python Version

The LeRobot codebase requires **Python 3.10+** for `|` type union syntax. macOS system Python is often 3.9 — don't use it.

```bash
# Use the project's venv (Python 3.12)
.venv/bin/python3 --version  # Should be 3.12.x
.venv/bin/pip3 install ...
```

### Dependency Installation (China)

Always use Tsinghua mirror for speed:

```bash
.venv/bin/pip3 install <pkg> \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn
```

Minimum deps for training:
```bash
.venv/bin/pip3 install torch torchvision \
  huggingface_hub datasets draccus accelerate \
  einops transformers Pillow gymnasium wandb \
  -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
```

Install lerobot itself (editable):
```bash
PYTHONPATH=src .venv/bin/pip3 install -e . --no-deps \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### HuggingFace Mirror

For downloading models/datasets in China:
```bash
export HF_ENDPOINT=https://hf-mirror.com
```
Set this before any `from_pretrained()` or dataset loading call.

### PyAV Compatibility

PyAV v18+ removed `av.option.Option`. The codebase's `pyav_utils.py` uses `av.option.Option` for type hints. Fix pattern:

```python
# Compatible _get_codec_options_by_name
try:
    return {opt.name: opt for opt in codec.descriptor.options}  # PyAV < 18
except AttributeError:
    return {str(opt): opt for opt in (codec.options or [])}     # PyAV >= 18
```

And change `av.option.Option` type hints to `Any` in function signatures.

## SmolVLA-LEW Policy Configuration

Policy features are configured via `PolicyFeature` objects, not raw shapes:

```python
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.smolvla_lew import SmolVLALewConfig, SmolVLALewPolicy

cfg = SmolVLALewConfig(
    input_features={
        "observation.image": PolicyFeature(FeatureType.VISUAL, (3, 64, 64)),
        "observation.state": PolicyFeature(FeatureType.STATE, (2,)),
    },
    output_features={
        "action": PolicyFeature(FeatureType.ACTION, (2,)),
    },
    smolvlm_name="HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    freeze_smolvlm=True,          # Only train action head
    action_hidden_size=256,
    action_num_layers=1,
    num_inference_timesteps=2,
    chunk_size=1,
    n_action_steps=1,
)
cfg.validate_features()  # Required before model init
model = SmolVLALewPolicy(cfg).to("mps")
```

## MPS GPU Training

Check MPS availability before training:
```python
import torch
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
model = model.to(DEVICE)
```

MPS works well for the action head (DiT-B, ~200K params). For the full SmolVLM backbone (500M params), MPS memory may be tight — use `freeze_smolvlm=True`.

## Training Flow

### 1. Synthetic Data (Quick Validation)

Before downloading large datasets, validate the training pipeline with synthetic data:

```python
torch.manual_seed(42)
synth_data = []
for _ in range(200):
    synth_data.append({
        "observation.image": torch.rand(3, 64, 64),
        "observation.state": torch.randn(2) * 0.5,
        "action": -0.5 * torch.randn(2) * 0.5 + torch.randn(2) * 0.1,
    })
```

Train a few epochs to verify loss decreases and model saves correctly. If loss doesn't drop, fix the pipeline before wasting time on real data downloads.

### 2. Batch Assembly

LeRobot policies expect batches as dicts with tensor values:
```python
batch = {}
for key in synth_data[0].keys():
    batch[key] = torch.stack([d[key] for d in batch_samples]).to(DEVICE)
```

### 3. Forward & Loss

```python
loss, output_dict = model.forward(batch)
optimizer.zero_grad()
loss.backward()
optimizer.step()
```

### 4. Inference

```python
model.eval()
with torch.no_grad():
    predicted_action = model.predict(batch)
```

### 5. Save

```python
model.save_pretrained(output_dir)
torch.save(config, f"{output_dir}/config.pt")
```

## Mini Model (No External Downloads)

When VLM weights can't be downloaded, build a miniature replacement:

```
TinyCNN(3×64×64) → 256-dim features
    +
State(2-dim)
    +
Timestep(1-dim) → DiT-MLP(261→256→256→2) → Action(2-dim)
```

Flow Matching loss: `|predicted_velocity - (noise_sample - clean_action)|²`

See `references/mini-model-architecture.md` for the complete implementation.

## Pre-trained Model Download & Inference

### Download Strategy (China / Slow Network)

HF `snapshot_download` often times out on large files (>500MB) even with mirror. Use **direct curl with resume**:

```bash
# For each large .safetensors file:
DEST=~/.cache/huggingface/hub/models--<org>--<model>/snapshots/<hash>
curl -L -C - --connect-timeout 30 --max-time 900 \
  "https://hf-mirror.com/<org>/<model>/resolve/main/model.safetensors" \
  -o "$DEST/model.safetensors"
```

The `-C -` flag resumes interrupted downloads — critical for files >1GB. Run multiple times until complete, then download small config files via `snapshot_download` with `allow_patterns`.

### SmolVLA Pre-trained Model

`lerobot/smolvla_base` (865MB policy + 1.9GB SmolVLM2 backbone = ~2.7GB total):

1. **Policy weights** (865MB): First `curl` the policy `model.safetensors` into the lerobot/smolvla_base snapshot
2. **VLM backbone** (1.9GB): Separately `curl` `HuggingFaceTB/SmolVLM2-500M-Video-Instruct/model.safetensors` into its snapshot
3. **Config files** (tiny): Use `HF_ENDPOINT=https://hf-mirror.com snapshot_download` with `allow_patterns=['config.json','*.json']`

Then place all files in the correct HF cache snapshots and load. The model loads its VLM backbone at init time (~6-8s on M1):

```python
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
policy = SmolVLAPolicy.from_pretrained('lerobot/smolvla_base')
```

### Model Loading Performance

- SmolVLM2-500M backbone: ~1.9GB on disk, loads in **6-8 seconds** on M1 MPS (measured: Python 3.12, torch 2.12, 489 weight tensors)
- `from_pretrained()` auto-places the model based on the config device; use `next(policy.parameters()).device` to check
- Inference is ~1.7s per `select_action()` on M1 MPS (VLM vision encoding + DiT flow matching)
- For pure action-head inference (frozen VLM), VLM is the bottleneck; total model in memory: ~450M params (~1.7 GB)

## Pitfalls

- **System Python is 3.9**: Don't use `/usr/bin/python3` — use `.venv/bin/python3` (3.12)
- **`av.option` removed in PyAV 18**: Patch `pyav_utils.py` (see above)
- **Missing `input_features`**: SmolVLALew expects `PolicyFeature` objects, not raw shapes dict
- **`validate_features()` not called**: Model init will fail with confusing error
- **HF timeout**: Set `HF_ENDPOINT=https://hf-mirror.com` before loading models; use curl -C for large files
- **SmolVLM 1.9GB download**: Use direct curl with resume; expect 15-20 minutes on mirror
- **Pre-trained model needs TWO downloads**: Policy weights AND VLM backbone are separate — both must be in HF cache
- **`num2words` required**: The SmolVLM processor needs `num2words` package; install with pip.

## Project Location

`~/lerobot-smolvla-lew/`

Key training scripts:
- `train_mini_v2.py` — CNN+DiT, no external downloads, 18s on MPS
- `train_synth.py` — Full SmolVLA-LEW with VLM backbone (needs download)

## Z-MAX Studio GUI

The project includes a full PyQt5 desktop application at `tools/gui/studio.py` (305KB). See `references/zmax-gui.md` for the complete module and layout overview.
