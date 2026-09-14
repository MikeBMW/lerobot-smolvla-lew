---
name: github-actions-ci
description: 'Use for GitHub Actions: Windows exe, Docker, ACR, releases.'
---

# GitHub Actions CI Workflows

Authoring multi-platform CI/CD pipelines on GitHub Actions, covering patterns and gotchas from building Z-MAX Console and Docker images.

## When to use

- Building Windows `.exe` from Python (PyInstaller) via CI
- Building & pushing Docker images (especially to Chinese registries like Alibaba Cloud ACR)
- Authoring workflows that push to GitHub Releases
- Diagnosing Windows runner checkout/Zone.Identifier failures
- Debugging workflow trigger conditions (tag push vs workflow_dispatch)

## Trigger patterns

```yaml
on:
  push:
    tags:
      - 'v*'                     # Tag push only
    paths:
      - 'tools/gui/**'           # Path filter
  workflow_dispatch:             # Manual trigger with tag input
    inputs:
      tag:
        description: 'Version tag'
        default: 'dev-snapshot'
```

**Pitfall**: When triggering via `workflow_dispatch`, `github.ref_name` is the branch name (e.g. `main`), NOT the tag. Use a dedicated step to determine the release tag:

```yaml
- name: Determine release tag
  id: release_tag
  shell: bash
  run: |
    if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
      echo "tag=${{ github.event.inputs.tag }}" >> $GITHUB_OUTPUT
    else
      echo "tag=${{ github.ref_name }}" >> $GITHUB_OUTPUT
    fi
```

## Windows .exe (PyInstaller) build

Full pipeline for a Windows runner:

```yaml
build:
  runs-on: windows-latest
  permissions:
    contents: write      # Required for Release upload
    actions: read
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - run: pip install pyinstaller PyQt5 numpy pillow
    - run: |
        cd tools\\gui
        # Convert PNG logo to .ico for exe icon
        python -c "from PIL import Image; Image.open('logo.png').save('logo.ico')"
        pyinstaller --onefile --windowed --icon logo.ico --name "AppName" studio.py
    - uses: actions/upload-artifact@v4
      with:
        name: AppName
        path: tools\\gui\\dist\\AppName.exe
    # Release upload (requires permissions.contents: write)
    - uses: svenstaro/upload-release-action@v2
      if: startsWith(github.ref, 'refs/tags/v') || github.event_name == 'workflow_dispatch'
      with:
        repo_token: ${{ secrets.GITHUB_TOKEN }}
        file: tools\\gui\\dist\\AppName.exe
        asset_name: AppName.exe
        tag: ${{ steps.release_tag.outputs.tag }}
        overwrite: true
```

## Windows runner: Zone.Identifier checkout fix

If a repo contains files with `:Zone.Identifier` suffix (Windows NTFS ADS artifacts), Windows runners fail checkout with `error: invalid path 'filename:Zone.Identifier'`.

**Fix:**

```bash
# 1. Find and remove from index
git ls-files | grep ':Zone.Identifier' | while read f; do git rm --cached "$f"; done

# 2. Delete physical files
rm -f *:Zone.Identifier

# 3. Add to .gitignore
echo '*:Zone.Identifier' >> .gitignore

# 4. Commit and re-tag
git commit -m "fix: remove Zone.Identifier ADS files"
git tag -f vX.Y.Z && git push origin vX.Y.Z --force
```

## Release 资产版本号（2026-08-26 发版实战踩坑）

PyInstaller 默认产物版本号是 **0.0.0**（macOS Info.plist 的 CFBundleShortVersionString、Windows exe 文件属性）。正式发版必须写真实版本：

**macOS（PlistBuddy，构建后、ditto 打包前）**：
```bash
cd tools/gui   # ⚠️ 必须 cd！workflow 每步是独立 shell，默认在仓库根
VER="${TAG#v}"  # tag 如 v3.2.0 → 3.2.0
# PyInstaller 默认 plist 有 CFBundleShortVersionString(0.0.0) 但【没有 CFBundleVersion】
# → 一律 Add 优先、Set 兜底
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" .../Info.plist 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VER" .../Info.plist
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VER" .../Info.plist 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VER" .../Info.plist
```

**Windows（--version-file）**：`--version-file` 路径是**相对 spec 文件所在目录**（tools/gui），不是 runner 工作目录！
- ✅ 把 version_info.txt 生成到 `tools/gui/version_info.txt`，命令里直接写 `--version-file version_info.txt`（此时已 cd tools/gui）
- ❌ 仓库根生成 + `--version-file ..\version_info.txt` → 实际找 `tools\gui\..\version_info.txt` = FileNotFoundError

**验证（发版必做，不能只看构建绿）**：下载资产用 API 且必须带 `Accept: application/octet-stream`，否则返回 JSON 元数据（1.8KB 假文件）：
```bash
curl -sL -H "Authorization: token $TOKEN" -H "Accept: application/octet-stream" \
  -o asset.zip "https://api.github.com/repos/O/R/releases/assets/$ASSET_ID"
```
资产 API 响应里有 `digest`（sha256），下载后 `sha256sum` 必须一致。macOS 架构用 `file` 查（Mach-O arm64 = M1 原生）；bundle 版本用 python plistlib 读 Info.plist（Linux 无 PlistBuddy/plutil）。

**下载路径坑（2026-08-26 发版实测，两条铁律）**：
1. **assets API 带 token 会被 WAF 拒 400**（公司网/代理环境实测）：`api.github.com/.../releases/assets/$ID` 带 `Authorization: token` 直接 400；但不带 token 的 `GET api.github.com/repos/O/R/releases/tags/vX.Y.Z`（拿 assets 列表 + 每项的 `digest` sha256 字段）是通的。→ **下载一律走 `browser_download_url` 直连**：
   ```bash
   curl -sL -o asset.zip "https://github.com/O/R/releases/download/vX.Y.Z/AssetName.exe"
   ```
2. **curl 跨域 302 必须 `-L`**：browser_download_url 会 302 到 S3/对象存储，不跟跳转就得到 302 空壳（几字节）；并发分块/断点续传（`-C -`）时尤其容易漏 `-L`。digest 对比：GitHub API 的 `digest` 字段格式是 `sha256:<hex>`，与本地 `sha256sum` 输出比对时先去掉 `sha256:` 前缀。

## Docker build & push to Alibaba Cloud ACR (China)

For users in mainland China, use Alibaba Cloud Container Registry (ACR) instead of Docker Hub.

```yaml
env:
  REGISTRY: registry.cn-hangzhou.aliyuncs.com
  NAMESPACE: zmax
  IMAGE: console

steps:
  - uses: docker/login-action@v3
    with:
      registry: ${{ env.REGISTRY }}
      username: ${{ secrets.ACR_USERNAME }}
      password: ${{ secrets.ACR_PASSWORD }}
  - uses: docker/build-push-action@v6
    with:
      context: tools/gui
      push: true
      tags: ${{ env.REGISTRY }}/${{ env.NAMESPACE }}/${{ env.IMAGE }}:v1.0.5
```

**Pitfall**: ACR login secrets must be configured as GitHub repo secrets: `ACR_USERNAME` and `ACR_PASSWORD`.

## YAML verification: PyYAML `on:` gotcha

GitHub Actions uses `on:` as the trigger key. PyYAML (used by Python-based verification scripts) **parses `on:` as boolean `True`**, causing `d.get("on")` to return `None`.

**Fix for verification scripts:**

```python
# PyYAML parses `on:` as boolean True
d = yaml.safe_load(workflow_yaml)
on_val = d.get("on") or d.get(True, {})
push_val = on_val.get("push", {})
tags = push_val.get("tags", [])
```

Alternatively, quote the key in the YAML file: `"on":` (valid in GitHub Actions, survives PyYAML).

## Docker: PyQt5 GUI in containers

For desktop PyQt5 apps in Docker:

- **WSL2/WSLg**: Mount `/tmp/.X11-unix:/tmp/.X11-unix` and set `-e DISPLAY=$DISPLAY`
- **Windows native (Docker Desktop + VcXsrv)**: Set `-e DISPLAY=host.docker.internal:0`, no X11 socket mount
- **Base image**: `python:3.12-slim` + `libxcb-xinerama0 libxkbcommon-x11-0 libgl1-mesa-glx libegl1-mesa`
- **Non-root user**: Use `ARG UID`/`ARG GID` to match host uid
