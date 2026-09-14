---
name: windows-app-deployment
description: >-
  Use when building Windows .exe via PyInstaller CI.
---

# Windows App Deployment — PyInstaller + GitHub Actions

## Overview

Package a PyQt5 (or any Python) desktop app into a single-file `.exe` via
GitHub Actions Windows runner. No local Windows environment needed — CI
does the build and uploads the artifact to Releases.

## Workflow skeleton

`.github/workflows/build-win-exe.yml`:

```yaml
name: Build Windows .exe
on: [push: {tags: [v*]}, workflow_dispatch: {inputs: {tag: {default: dev-snapshot}}}]
jobs:
  build:
    runs-on: windows-latest
    permissions: {contents: write, actions: read}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5 with: {python-version: "3.12"}
      - run: pip install pyinstaller PyQt5 numpy pillow grpcio protobuf python-pptx
      - run: >
          cd tools\\gui &&
          pyinstaller --onefile --windowed --icon logo.ico
          --name "MyApp"
          --add-data "logo.png;." --add-data "helper.py;."
          studio.py
      - uses: actions/upload-artifact@v4
        with: {name: MyApp, path: "tools\\gui\\dist\\MyApp.exe", compression-level: 0}
      - name: Determine tag
        id: reltag; shell: bash
        run: >
          if [ "${{ github.event_name }}" = "workflow_dispatch" ];
          then echo "tag=${{ inputs.tag }}" >> $GITHUB_OUTPUT;
          else echo "tag=${{ github.ref_name }}" >> $GITHUB_OUTPUT; fi
      - uses: svenstaro/upload-release-action@v2
        if: startsWith(github.ref, 'refs/tags/v') || github.event_name == 'workflow_dispatch'
        with:
          repo_token: ${{ secrets.GITHUB_TOKEN }}
          file: "tools\\gui\\dist\\MyApp.exe"
          asset_name: MyApp.exe
          tag: ${{ steps.reltag.outputs.tag }}
```

## Pitfalls

### 1. Zone.Identifier → Windows checkout failure

```
error: invalid path 'docs/foo.zip:Zone.Identifier'
```

**Fix:** Remove from git index; add to `.gitignore`:
```gitignore
*:Zone.Identifier
```

### 2. PyYAML `on:` → boolean True

Quote it: `"on"` in workflow YAML. GitHub's parser handles both.

### 3. Release upload needs `contents: write` permission

Without it the GITHUB_TOKEN can't upload assets.

### 4. Heavy ML imports (torch, lerobot) blow up .exe size

Guard imports to keep the base .exe small:
```python
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

if _TORCH_AVAILABLE:
    from lerobot.transport import services_pb2
```

### 5. --add-data for every local module

PyInstaller doesn't auto-detect local `.py` files imported dynamically.
List them all with `--add-data "mod.py;."`.

### 6. workflow_dispatch needs explicit tag step

`github.ref_name` is the branch name on dispatch, not the tag.
Use a dedicated step to determine the correct release tag.
