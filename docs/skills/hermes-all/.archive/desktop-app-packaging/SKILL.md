---
name: desktop-app-packaging
title: Desktop App Packaging
description: >-
  Package PyQt5 desktop apps — Docker X11, Windows .exe.
---

# Desktop App Packaging

Workflows for distributing a PyQt5 desktop application.

## 1. Docker (Linux / WSLg)

Lightweight container mounting host X11 socket.

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb-xinerama0 libxkbcommon-x11-0 libgl1-mesa-glx libegl1-mesa \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir PyQt5 numpy pillow
ARG UID=1000 ARG GID=1000
RUN groupadd -g $GID xspace && useradd -m -u $UID -g $GID xspace
USER xspace
WORKDIR /home/xspace
COPY --chown=xspace:xspace . /home/xspace/console/
CMD ["python3", "/home/xspace/console/studio.py"]
```

**Run**: `docker run --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix zmax-console`

### Registry (China)

Alibaba Cloud ACR (`registry.cn-hangzhou.aliyuncs.com`). Docker Hub unreliable from China.

## 2. Windows .exe (PyInstaller + GitHub Actions)

Cross-compile on `windows-latest` runner.

```yaml
jobs:
  build:
    runs-on: windows-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: python-version: "3.12"
      - run: pip install pyinstaller PyQt5 numpy pillow grpcio protobuf
      - run: |
          cd tools\gui
          python -c "from PIL import Image; Image.open('logo.png').save('logo.ico')"
          pyinstaller --onefile --windowed --icon logo.ico --name AppName --add-data "logo.png;." studio.py
      - uses: actions/upload-artifact@v4
      - id: release_tag
        shell: bash
        run: |
          [ "${{ github.event_name }}" = "workflow_dispatch" ] \
            && echo "tag=${{ github.event.inputs.tag }}" >> $GITHUB_OUTPUT \
            || echo "tag=${{ github.ref_name }}" >> $GITHUB_OUTPUT
      - uses: svenstaro/upload-release-action@v2
        with:
          tag: ${{ steps.release_tag.outputs.tag }}
```

### Common pitfalls

| Problem | Fix |
|---|---|
| Checkout fails on Windows | Remove `:Zone.Identifier` ADS files; `.gitignore` `*:Zone.Identifier` |
| Upload to Release fails | Need `permissions: contents: write` |
| workflow_dispatch skips release | Use explicit `release_tag` step |

## 3. Graceful Torch/Lerobot Imports

Too large for .exe (~GB). Guard with try/except:

```python
try: import torch; _TORCH_AVAILABLE = True
except ImportError: _TORCH_AVAILABLE = False
```

Detect frozen: `getattr(sys, 'frozen', False)`.

## 4. Document Distribution

- **Online fallback**: frozen .exe → GitHub raw URLs
- **Sync**: download to `%LOCALAPPDATA%\zmax\docs\`
- **Path**: frozen → app data; source → `repo/docs/`

## 5. Zone.Identifier ADS Cleanup

```bash
git ls-files | grep ':Zone.Identifier'
git rm --cached "./path:Zone.Identifier"
echo '*:Zone.Identifier' >> .gitignore
```
