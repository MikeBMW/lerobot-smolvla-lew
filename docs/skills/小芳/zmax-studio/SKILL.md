---
name: zmax-studio
description: Launch and troubleshoot Z-MAX Studio GUI — PyQt5 training/inference IDE, PluginScene fix, screenshot capture
platforms: [macos]
---

# Z-MAX Studio GUI

Z-MAX Studio is a PyQt5-based integrated development environment for robot learning. It provides a dashboard for dataset management, SmolVLA training, evaluation, hardware toolbox, and inference services.

## Quick Start

```bash
cd ~/lerobot-smolvla-lew/tools/gui
PYTHONPATH=../../src ../../.venv/bin/python3.12 studio.py
```

## Requirements

```bash
pip install PyQt5 PyQt5-sip grpcio grpcio-tools -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
```

## Architecture

8 functional modules accessed via sidebar navigation:

| Module | System | Function |
|--------|--------|----------|
| Dataset Manager | System 2 | 12 robot datasets, download/delete/view |
| Training Console | Sys-11 | SmolVLA 30+ parameters, one-click train |
| Evaluation | Sys-12 | LeWorldModel validation, replay |
| Hardware Toolbox | System 0 | Motor/camera/force/estop, simulation |
| Config Center | Sys-11+12 | SmolVLALewConfig visual editor |
| Real-time Monitor | Sys-11+12 | Training curves, GPU, latency |
| Version Sync | — | Upstream update check, safe sync |
| Inference Service | Sys-11 | gRPC PolicyServer, ~270ms/frame |

## Known Issues & Fixes

### PluginScene Class Corruption
The `PluggableSceneModule` class in `studio.py` had a corrupted `__init__` around line 6154. The code block:
```python
"""Z700插拔场景..."""
def __init__(self):
    super().__init__("插拔场景 · Z700", [...])
```
was a stray method from a deleted class, causing `TypeError: QWidget argument 1 has unexpected type 'str'`.

**Fix**: Comment out the entire broken block (docstring + __init__ + body). The scene module is under development and not critical for core functionality.

### Missing Dependencies
- `ModuleNotFoundError: num2words` → `pip install num2words`
- `ModuleNotFoundError: grpc` → `pip install grpcio grpcio-tools`

### CSS Warnings
`Unknown property cursor` warnings are harmless PyQt5 CSS parsing artifacts. No fix needed.

## Screenshot Capture

When running headless or via messaging platform, use the `mss` library to capture the display:

```bash
pip install mss pillow
python3.12 -c "
import mss, mss.tools
with mss.mss() as sct:
    img = sct.grab(sct.monitors[1])
    mss.tools.to_png(img.rgb, img.size, output='/Users/mikeni/zmax_gui.png')
"
```
Note: `screencapture` CLI requires Screen Recording permission which terminal may lack. `mss` works without it.
