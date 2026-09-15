---
name: pyqt5-distribution
description: Package PyQt5 apps — Docker X11, Windows .exe CI, doc sync, auto-update, PPT instruction engine.
---

# PyQt5 Desktop App Distribution

Package a PyQt5 (or any Python GUI) desktop application into:
1. **Lightweight Docker image** — X11 host socket mount (no VNC needed)
2. **Windows standalone .exe** — PyInstaller via CI
3. **GitHub Actions automation** — tag-triggered builds for both

## Docker — X11 Host Socket (轻量)

**Best for**: WSL2 (WSLg), Linux desktops. No VNC, no browser.

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb-xinerama0 libxkbcommon-x11-0 \
    libgl1-mesa-glx libegl1-mesa libdbus-1-3 fontconfig \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir PyQt5 numpy pillow
ARG UID=1000; ARG GID=1000
RUN groupadd -g $GID xspace && useradd -m -u $UID -g $GID xspace
USER xspace; WORKDIR /home/xspace
COPY --chown=xspace:xspace . /home/xspace/console/
CMD ["python3", "/home/xspace/console/studio.py"]
```

Run:
```bash
docker run --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix image-name
```

## Windows .exe — PyInstaller via CI

**Best for**: Windows users. Zero install, single .exe.

Create `.github/workflows/build-win-exe.yml` with `windows-latest` runner. Key steps:
- `pip install pyinstaller PyQt5 numpy pillow grpcio protobuf python-pptx`
- `pyinstaller --onefile --windowed --icon logo.ico --name "AppName" --add-data "mod1.py;." --add-data "mod2.py;." studio.py`
- Upload artifact + attach to Release on tag

**GITHUB_TOKEN permissions**: Add `permissions: { contents: write, actions: read }` to the job, otherwise release upload will fail with "Resource not accessible by integration".

**Tag determination**: For workflow_dispatch, `github.ref_name` is the branch name, not the tag. Add a dedicated step.

**Graceful dependency handling**: If the app imports heavy modules (torch, transformers, lerobot), the .exe will bundle them or crash. For features that need CUDA (won't work on most Windows), wrap imports in try/except.

**Local module discovery**: PyInstaller doesn't auto-detect local `.py` files imported dynamically. List ALL local modules with `--add-data "mod.py;."` for each one.

**Logo format**: PyInstaller `--icon` needs `.ico`. Convert: `python -c "from PIL import Image; Image.open('logo.png').save('logo.ico')"`.

### Architecture Module (L2/L3/L4 Product Comparison)

Render a three-column comparison of L2/L3/L4 product architectures using QFrames with styled backgrounds. Each column shows the same three-layer structure (SYS2 → SYS1[SYS11+SYS12] → SYS0) but with different capabilities per level.

**Layout:** horizontal 3-column (L2 | L3 | L4), each column has vertical stacked layers:
- SYS 2 (top bar, single color) → arrow → SYS 1 (translucent container with SYS11+SYS12 sub-boxes) → arrow → SYS 0 (bottom bar, red)

**Data structure pattern (critical for tuple unpacking):**

```python
levels = [
    ("L2 基线", "Z700F", SYS0_COLOR, [
        ("SYS 2", "云端训练", SYS2_COLOR,
         ["离线训练\n轻量模型"]),
        ("SYS 1", "边缘推理", SYS11_COLOR,    # MUST have 4 fields
         [("SYS 10", "ACT", C_CYAN),      # sub-box: (sid, desc, color)
          ("SYS 12", "—", C_GRAY)]),
        ("SYS 0", "硬件执行", C_RED,
         ["固定工位\n力控1kHz\n视觉定位"]),
    ]),
    # L3, L4 — same structure
]
```

**CRITICAL: SYS1 entries MUST have 4 fields** — `("SYS 1", "边缘推理", color, [...sub-boxes...])`. Omitting the description string causes `ValueError: not enough values to unpack (expected 4, got 3)` at runtime.

**Helper methods:**

```python
def _level_card(self, label, model, accent, layers):
    card = QFrame()
    card.setStyleSheet(f"background:{C_BG2}; border:1px solid {accent}66; border-radius:10px;")

def _layer_box(self, sys_id, desc, color, items):
    f.setStyleSheet(f"background:{color}; border:1px solid {color}88; border-radius:6px;")
    f.setFixedHeight(90)

def _sys1_box(self, sys_id, desc, color, sub_boxes):
    # Translucent bg with alpha "33" so parent border shows through
    f.setStyleSheet(f"background:{color}33; border:2px solid {color}88; border-radius:6px;")
    for sid, sdesc, sc in sub_boxes:
        sb.setStyleSheet(f"background:{sc}; border-radius:4px;")
```

Each column added with `cols.addWidget(card, 1)` inside a `QHBoxLayout cols`.

### PPT Slide Native Shapes (Zone.Identifier)

Draw Z-MAX three-layer architecture on an existing PPTX using python-pptx native shapes:

```python
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE

prs = Presentation("existing.pptx")
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout

# Set dark background
bg = slide.background; bg.fill.solid(); bg.fill.fore_color.rgb = RGBColor(0x06, 0x08, 0x0D)

# Rounded rectangle card
shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
shape.fill.solid(); shape.fill.fore_color.rgb = RGBColor(0x0D, 0x11, 0x17)
shape.line.color.rgb = RGBColor(0x00, 0xD4, 0xAA); shape.line.width = Pt(1)
shape.adjustments[0] = 0.05

# Text box
txBox = slide.shapes.add_textbox(left, top, width, height)
tf = txBox.text_frame; p = tf.paragraphs[0]; p.text = "Title"
p.font.size = Pt(12); p.font.color.rgb = RGBColor(0xE6, 0xED, 0xF3)

# Connector arrow (Triangle tail end) — use _element on connector, NOT line._element
conn = slide.shapes.add_connector(1, x1, y1, x2, y2)  # 1 = straight
conn.line.color.rgb = accent_color; conn.line.width = Pt(2)
import lxml.etree as etree
ln = conn._element.find('{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
if ln is None:
    ln = etree.SubElement(conn._element,
        '{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
tail = etree.SubElement(ln,
    '{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd')
tail.set('type', 'triangle'); tail.set('w', 'med'); tail.set('len', 'med')
```

Three-layer architecture pattern:
- Three equal-width columns: System 2 (purple #A371F7), System 1 (blue #58A6FF), System 0 (green #3FB950)
- Each column has accent bar at top + item rows with alternating row backgrounds
- Downward arrows between columns for model deploy flow
- Right-side data feedback panel (orange #F7A90B) with state/torque/image return
- Bottom legend with colored dots
- Top-right marker shape: `V 静` in orange rounded rect

## macOS .app — PyInstaller via CI (2026-08-25 实测)

一次 tag 推送并行出双平台产物: 同一个 workflow 两个 job (`windows-latest` + `macos-latest`),
各自 `svenstaro/upload-release-action@v2` (overwrite: true) 挂到**同一个 Release**。

## 3D 视图打包 — pyqtgraph + PyOpenGL (2026-08-26 v3.2.3 实测)

**坑**: 3D 视图 (GLViewWidget) 依赖 pyqtgraph + PyOpenGL, PyInstaller **不会自动收集** → exe 裸报 `No module named pyqtgraph`。
**修复**: 双平台 pip install 都加 `pyqtgraph PyOpenGL`, pyinstaller 加 `--collect-all pyqtgraph --collect-all OpenGL`。

```bash
# Windows job pip install
pip install pyinstaller "PyQt5==5.15.11" numpy pillow grpcio protobuf python-pptx pyqtgraph PyOpenGL
# macOS job pip install (同样加 pyqtgraph PyOpenGL)

# Windows pyinstaller
pyinstaller --onefile --windowed --icon logo.ico --name "Z-MAX_Console" \
  --collect-all pyqtgraph --collect-all OpenGL \
  --add-data "mod1.py;." --add-data "mod2.py;." studio.py
# macOS pyinstaller
pyinstaller --windowed --icon logo.icns --name "Z-MAX_Console" \
  --collect-all pyqtgraph --collect-all OpenGL \
  --add-data "logo.png:." --add-data "docs_sync.py:." studio.py
```

要点:
- `--collect-all pyqtgraph --collect-all OpenGL` 必加, 否则 3D 视图裸报 ModuleNotFoundError
- 本地 gui-venv311 实测: pyqtgraph 0.14.0 + PyOpenGL 3.1.10, DreamView3D 可构造
- 旧 exe 报错提示优化: 捕获 `No module named pyqtgraph/OpenGL` → 弹「当前 exe 是旧版, 请检查更新」
- 源码模式 (python studio.py) 需手动 `pip install pyqtgraph PyOpenGL`
- Windows exe ~77MB, macOS zip ~58MB (含 pyqtgraph 后体积)
- 验证: 打开「🧭 3D 视图」正常渲染 = 打包成功; 两个 job 都 success + 本地 gui-venv311 可构造: 同一个 workflow 两个 job (`windows-latest` + `macos-latest`),
各自 `svenstaro/upload-release-action@v2` (overwrite: true) 挂到**同一个 Release**。

```yaml
  build-mac:
    runs-on: macos-latest          # arm64 (Apple Silicon)
    permissions: { contents: write, actions: read }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install pyinstaller "PyQt5==5.15.11" numpy pillow grpcio protobuf python-pptx
      - name: Make .icns (PyInstaller 在 mac 只认 .icns)
        run: |
          cd tools/gui && mkdir -p logo.iconset
          for s in 16 32 64 128 256 512; do
            sips -z $s $s logo.png --out logo.iconset/icon_${s}x${s}.png
            d=$((s*2)); sips -z $d $d logo.png --out logo.iconset/icon_${s}x${s}@2x.png
          done
          iconutil -c icns logo.iconset -o logo.icns
      - run: |
          cd tools/gui
          pyinstaller --windowed --icon logo.icns --name "Z-MAX_Console" \
            --add-data "logo.png:." --add-data "docs_sync.py:." studio.py
      - name: Zip .app
        run: |
          cd tools/gui/dist
          ditto -c -k --sequesterRsrc --keepParent "Z-MAX_Console.app" "Z-MAX_Console-macOS.zip"
```

mac 打包要点 (和 Windows 不一样的地方):
- `--add-data` 分隔符是 **冒号** `src:dest` (Windows 是分号 `src;dest`) — 写错不报错但资源丢失
- 图标必须 `.icns`: `sips` 生成多尺寸 → `iconutil -c icns`; 直接给 .png/.ico 会构建失败
- `--windowed` 产出 `dist/App.app` (目录包), **必须用 `ditto -c -k --keepParent` 压缩**;
  普通 `zip` 会丢可执行权限/资源分叉 → 用户解压后双击无反应
- 未签名/未公证 → Gatekeeper 拦: Release 说明里写明「右键 → 打开」或 隐私与安全性 → 仍要打开
- PyQt5 在 arm64 需 ≥5.15.10 的 wheel, 建议 pin `PyQt5==5.15.11`; 老版本无 arm64 wheel 会去编译源码超时
- arm64 产物在 Intel Mac 上跑不了 (反之 Rosetta 可以) → Release 说明标清架构

Docker Hub is unreliable from China. Use Alibaba Cloud ACR:
- Registry: `registry.cn-hangzhou.aliyuncs.com`
- Secrets: `ACR_USERNAME`, `ACR_PASSWORD`
- Use `docker/login-action@v3` with `registry:` set to ACR

## Document Distribution & Sync

When the GUI includes help docs (training manuals, product docs), design a **self-syncing document system** with online fallback.

### Architecture

```
.exe dir/
├── Z-MAX_Console.exe
└── 静界/              ← user-named docs root
    ├── .version        ← JSON: version, last_sync, doc_count, hash
    ├── 01-培训/         ← classified by filename prefix
    ├── 02-解决方案/
    ├── 03-训练模型/
    ├── 04-运维部署/
    ├── 05-开发参考/
    ├── 06-发布品牌/
    └── 07-供应链/
```

### Key Design Decisions

**动态文件发现** — Don't hardcode a manifest. Use **GitHub Contents API** to list files at sync time. Exclude dirs: source/, skills/, archive/, memory/, screenshots/, web/, test-reports/, survey/, patents/.

**分类路由** — Route files by filename prefix into numbered categories via `ROUTING_RULES`. Uncategorized → `00-其他`.

**版本追踪** — `.version` file records `last_sync`, `doc_count`, `hash` (MD5 of directory). Compare hashes to detect local changes on next sync.

**路径策略** — `get_docs_dir()`:
- Frozen (.exe): next to executable → if exe in temp dir, fallback to `%LOCALAPPDATA%\zmax\静界`
- Source: repo root/静界/

**打开文档目录**: Must call `os.makedirs(path, exist_ok=True)` before opening via `QDesktopServices.openUrl(QUrl.fromLocalFile(path))`, otherwise a non-existent directory silently does nothing.

### Frozen .exe Document Opening

When user clicks a help doc in frozen mode:
1. Open **GitHub tree URL** (`/tree/main/docs`) via `QDesktopServices.openUrl`
2. User downloads locally via 📥 同步文档
3. 📂 打开文档目录 opens the local 静界/ folder

## Auto-Update System

Add self-update capability to PyInstaller Windows .exe.

### Components

- `update_checker.py` — `check_latest()`, `download_update()`, `check_in_background()`
- Menu: **关于 → 🔄 检查更新**
- Home page: **⬆ 升级** button (use signal pattern to reach main window)
- Startup: `QTimer.singleShot(5000, self._auto_check_update)` background check

### Flow

1. Background check → GitHub `/releases/latest` API → compare with `CURRENT_VERSION`
2. If newer: status bar notification
3. Manual check: three-button `QMessageBox` → **下载并升级** / **打开下载页** / **稍后**
4. Auto-download: `download_update()` streams to `%TEMP%/zmax_update/`
5. Creates `upgrade.bat` that waits 2s, copies new.exe over old.exe, launches it, self-deletes

### Guard

```python
CURRENT_VERSION = "v1.0.6"
API_RELEASES = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
```

Background check silently swallows exceptions (network down = no notification).

### Version Bump Checklist

**CRITICAL**: Version must be bumped in FOUR files simultaneously (miss one → Release tag says vX.Y.Z but the .exe window title/version shows old):
- `studio.py` → `setWindowTitle(f"... vX.Y.Z ...")` ← most commonly missed (title shows old while tag is new)
- `update_checker.py` → `CURRENT_VERSION`
- `version_sync.py` → `zmax_ver`
- `docs_sync.py` → `"version"` meta + `zmax_version`

**NEVER force-push the same tag number** — use a NEW distinct tag per release (v1.0.5 → v1.0.6 → v1.0.7). Old tags stay available; old .exe's auto-updater detects the new version naturally. If the tag already exists (push fails "already exists"), trigger rebuild with workflow_dispatch: `POST /actions/workflows/build-win-exe.yml/dispatches {"ref":"main","inputs":{"tag":"vX.Y.Z"}}` — the upload-release action's `overwrite: true` replaces the asset on the existing Release. Verify via API: GET `/releases/tags/{tag}` → assets[].browser_download_url, and check Actions run conclusion=success before posting the download link.

### gh CLI 未安装时的 Release 全流程（curl + GitHub API）
WSL 常无 `gh` CLI。用 curl + API 走完整 release 流程（push tag → 轮询 → 验证 → 发链接）:
```bash
# token 从 ~/.git-credentials 提取 — 格式 https://user:TOKEN@github.com → TOKEN 在冒号后、@ 前
TOKEN=$(python3 -c "
import re; s = open('/home/xspace/.git-credentials').read()
m = re.search(r'https://[^:]+:([^@]+)@github', s)
print(m.group(1) if m else '')")
# 触发: git tag vX.Y.Z && git push origin vX.Y.Z  (build-win-exe.yml on: tags v*)
# 轮询 Actions run (找 'Build Windows' 的 run, status/conclusion):
curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=8"
# 验证 Release 资产 (再发链接):
curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/<owner>/<repo>/releases/tags/vX.Y.Z"
```
- 坑: 误传 `Authorization: token MikeBMW:TOKEN`（把 user 也带进 token）→ API 返回空/401；**只取冒号后**
- Windows 构建 ~2.5-4 分钟（pyinstaller + pip 安装），用后台轮询 + notify_on_complete 而不是前台长等
- 发布顺序: push code → push tag（触发构建）→ 轮询 completed success → GET release 拿 browser_download_url → 才发飞书/群链接

## PPT Instruction Engine

Users write commands as PPT slides → app parses → drives actions.

| Verb | Action |
|------|--------|
| CREATE_FILE | Write document to docs directory |
| RUN_CMD | Execute shell command |
| TRAIN_MODEL | Queue training task |
| GIT_COMMIT | Commit + push to GitHub |
| DEPLOY | Deploy to server |
| EVAL_MODEL | Run evaluation |
| UPDATE_CONFIG | Modify config |

Slide structure: **Title** = `VERB: Instruction name`, **Body** = parameters.

Menu: **🎯 PPT 指令控制** → 生成模板 / 解析执行 / 打开目录

### PPT Marker Convention

When user marks PPT slides with a symbol in top-right corner, the agent detects and acts:

| Marker | Meaning |
|--------|---------|
| `V 静` | Draw System 2→1→0 architecture on this slide using PPT native shapes |
| `V 指令` | Execute the slide's instruction via ppt_engine |

The agent uses `python-pptx` to add a new slide.

**CRITICAL: NEVER build shapes from scratch when modifying an existing deck.**
Building shapes programmatically (rounded rects, text boxes, connectors) will NEVER match the user's template, no matter how carefully you replicate colors. The result will look visibly wrong and the user will reject it with "样式没对上" (style doesn't match).

**Template inspection workflow (MANDATORY before creating any PPT slide):**

```python
# 1. Check the template's background and text colors
for slide_idx in range(3):  # inspect first 3 slides
    slide = list(prs.slides)[slide_idx]
    try:
        bg = slide.background.fill.fore_color.rgb
        print(f"bg=#{bg}")
    except: pass
    for sh in slide.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip():
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    print(f"text_color=#{r.font.color.rgb}")
            break

# 2. Find the correct layout — DON'T use BLANK (index 6)
# Check for custom layouts in slide masters:
for mi, master in enumerate(prs.slide_masters):
    for li, layout in enumerate(master.slide_layouts):
        print(f'  Master {mi}, Layout {li}: "{layout.name}"')

# 3. Use the custom layout (e.g. "横线") for new slides
hengxian = prs.slide_masters[1].slide_layouts[4]  # find the right one
sd = prs.slides.add_slide(hengxian)  # inherits correct theme/bg/placeholders
```

**Correct approaches (in priority order):**

**A. Clone an existing content slide (PREFERRED):**
```python
import copy
template_slide = list(prs.slides)[8]  # pick a content slide the user likes
new_elem = copy.deepcopy(template_slide._element)
rId = prs.part.next_rId  # may need alternate approach for this version
# Alternative: use prs.slides.add_slide() with layout, then clear shapes
```

**B. Use a named custom layout + add content on top:**
```python
# Find custom layout by name (NOT default BLANK layout)
hengxian = prs.slide_masters[1].slide_layouts[4]  # "横线" in user's deck
sd = prs.slides.add_slide(hengxian)
# Now add shapes on top — the layout provides background/theme
```

**C. If the user has ALREADY drawn their own layout on a slide, replicate it EXACTLY:**
```python
# Read the user's slide shapes — position, size, fill, border, text
# Then recreate with identical parameters
for sh in user_drawn_slide.shapes:
    print(f"type={sh.shape_type} pos=({sh.left},{sh.top}) size=({sh.width}x{sh.height})")
    print(f"fill=#{sh.fill.fore_color.rgb} border=#{sh.line.color.rgb}")
```

**Key template colors observed in a real white-template deck:**
- Background: #FFFFFF (white)
- Title text: #002060 (dark blue)
- Body text: #000000 (black)
- Accent: #0070C0 (blue)
- Orange accent: #F7A90B
- SYS0 red: #C00000 (specific to Z-MAX)
- SYS2 purple: #7B2DC0
- SYS1 blue: #4472C4
- SYS0 green: #2E7D32

**NEVER use the console's dark theme colors** (#06080d, #0d1117, #00d4aa) in a white-template PPT.**

**When the user says "I've already drawn it on slide X, replicate that":** Read every shape property (position, size, fill, border, text) from their slide and reproduce with identical parameters. Do NOT interpret, improve, or redesign. Exact match only.

**Finding the right layout**: Check `slide_masters[i].slide_layouts[j]` for custom layout names:
```python
for mi, master in enumerate(prs.slide_masters):
    for li, layout in enumerate(master.slide_layouts):
        print(f'  Master {mi}, Layout {li}: \"{layout.name}\"')
```
If the user's slides use a named custom layout (e.g. "横线"), use that layout for new slides via `prs.slides.add_slide(master.slide_layouts[li])`. The layout provides the correct background, placeholders, and theme inheritance — you only add content shapes on top.

**CRITICAL: Match the target PPT's template, NOT the console's dark theme.** The agent's default dark bg (#06080d) will NOT match a white/light template. Always inspect the first 3 slides first:

1. Read background: `slide.background.fill.fore_color.rgb`
2. Read text color: `list(slide.shapes)[0].text_frame.paragraphs[0].runs[0].font.color.rgb`
3. Check accent fills: look for `fill.fore_color.rgb` on shapes
4. Typical white template: bg=#FFFFFF, text=#000000, accents=#0070C0 blue or #F7A90B orange
5. Use the template's palette, not the console's dark palette

**Overwriting**: Clear all shapes before re-drawing:
```python
for sh in list(slide.shapes):
    sh._element.getparent().remove(sh._element)
slide.background.fill.solid()
slide.background.fill.fore_color.rgb = WHITE  # match template
```

## 视频资源打包 — MLP 操作视频进 exe (2026-08-27 v3.2.4 实测)

**场景**: 控制台「🎥 操作视频」节点需要 reports/*MLP*.mp4, 但 reports/ 被 .gitignore (视频不进库铁律) → CI checkout 无视频 → exe 里 glob 空 → 用户看到 "无 MLP 操作视频"。

**方案 = CI 从 ECS 下载 + --add-data**:
1. 视频生成 (tools/gen_insert_video.py) → 预抽帧缓存 (播放器检测 `reports/_mlp_cache_<名>/` 帧数>10 直接播, **Windows exe 无 ffmpeg, 不预抽帧就播不了** — 抽帧依赖外部 ffmpeg, Windows 没有 → "抽帧失败")
2. 视频+缓存 zip 上传 ECS 静态目录 (root@39.102.211.79:/www/wwwroot/datadrive.world/models/ + chmod 644, 走已验证的 /models/ nginx 静态 location 绕过 PHP)
3. workflow 每 job 加 Download step: `curl -fsSL -o mlp_video_pack.zip <url>` + `python -m zipfile -e mlp_video_pack.zip reports/` (win/mac 都要, shell: bash)
4. --add-data: win `"$env:GITHUB_WORKSPACE\reports\mlp_insert_success_final.mp4;reports"` + 缓存目录; mac 冒号分隔
5. 播放器 frozen 路径已支持: `_repo_root()` frozen → `sys._MEIPASS`, glob `reports/*mlp*` 命中 _MEIPASS 内资源

**坑 (都踩过)**:
- **zip 解压目标**: zip 内是平级路径 (`mlp_insert_success_final.mp4` + `_mlp_cache_.../`), 解压到 `.` 会落到工作区根而**不是 reports/** → 后续 ls 验证 exit 2 失败 (bash -e pipefail) + --add-data 路径不存在 → PyInstaller 失败。必须 `-e xxx.zip reports/`
- 预抽帧要 **fps=10 + scale=960** (全量抽帧 355 帧 59MB 太大; 播放器 100ms/帧, 10fps 帧 = 播放时长与视频一致; JPEG 每帧 ~25KB)
- gen_insert_video.py 默认输出 insert_success_demo.mp4 (播放器 _PRIORITY 第一); 标准 MLP 名 mlp_insert_success_final.mp4 需脚本同步 copy2 一份 (08-27 已加)
- 视频上传 ECS 后必须 curl 验证 MD5 一致 (nginx/PHP 截断历史坑)
- workflow_dispatch 可重触发同 tag 构建 (upload-release-action overwrite:true 替换资产), 不用改 tag 号

## 引擎类依赖 (mujoco/metaworld) 打包 — 数据资产 + frozen 路径 (2026-09-11 实测)

三类必踩坑, 全部表现为"源码跑得通, exe 里点运行没轨迹/没动画":

1. **数据资产不进包** — `metaworld` 运行时用 `Path(__file__).parent/assets/*.xml` 读模型 (非 importlib.resources),
   而 PyInstaller **只自动收 .py**, 资产缺失 → `File ... does not exist`。**Windows 与 mac 的 pyinstaller 命令行必须一致地带**
   `--hidden-import metaworld --hidden-import mujoco --collect-all metaworld --collect-all mujoco`
   (本项目曾只在 mac 加 → Windows 点运行必失败)。
   验证: `python -m PyInstaller.utils.cliutils.archive_viewer -r -b dist/App.exe | grep sawyer_xyz` (onefile 也能列出数据文件),
   **把它写成 CI 步骤, 资产缺失即 fail** (防回归)。.app (onedir) 用 `find App.app -name '*.xml' | wc -l`。

2. **frozen 下 `__file__` 不在仓库里** — 模块在 PYZ 里, `__file__ = _MEIPASS/xxx.pyc`
   → `dirname(dirname(__file__))` 得到的是**临时目录的父级** → 找同仓库脚本 (`tools/gen_*.py`) 永远失败。
   做法: 统一 `frozen → sys._MEIPASS`, 并写多候选探测器 (包根/_MEIPASS/tools/源码 tools), 例如
   ```python
   def _tool_script(name):
       root = _repo_root_path()          # frozen → _MEIPASS
       mp = getattr(sys, "_MEIPASS", "") or ""
       for c in (os.path.join(root,"tools",name), os.path.join(root,name),
                 os.path.join(mp,name), os.path.join(mp,"tools",name)):
           if os.path.isfile(c): return os.path.abspath(c)
       return os.path.join(root,"tools",name)
   ```
   子进程生成器还要统一**输出根** (`env ZMAX_*_ROOT=root` + 脚本内 `makedirs(REP)`), 否则生成器写到临时目录父级,
   GUI 找不到产物 → "视频已生成(上传失败)"。

3. **子进程里禁止 `sys.executable`** — PyInstaller 下 = app 二进制本身, 起它就是新开一个 app 实例 (用户侧"反复重启")。
   用 `resolve_python()`; 需要仓库脚本时的 frozen 分支直接跳过 (由 CI 预生成 + 随包)。

4. **Windows cp1252 控制台编码** — 脚本里的 `print("✅ 写入: ...")` 在 Windows 控制台/CI (bash 步骤) 抛
   `UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'` → **exit 1** (CI 步骤实测失败, 文件其实已写好);
   GUI 用 `subprocess(capture_output=True)` 调同一脚本时同样崩 = 静默"视频生成失败"。双保险:
   脚本顶部 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` + 父进程 env 传 `PYTHONIOENCODING=utf-8`。

## 坑: mujoco 自带插件 DLL 在 frozen 包里解析不到依赖 (2026-09-15 Windows 实锤修)

**症状** (exe 里点「真实化运行」即失败):
`Failed to load dynlib/dll '...\_MEI00000d042\mujoco\plugin\actuator.dll'.
Most likely this dynlib/dll was not found when the application was frozen.`

**别被这句话骗 —— 文件其实在包里**。`--collect-all mujoco` 收集没问题, 但布局是:
- `_MEIPASS/mujoco/mujoco.dll` (运行时库, 在 mujoco/ 这一级)
- `_MEIPASS/mujoco/plugin/actuator.dll` (插件, 在下一级)
而 `actuator.dll` 的 PE 导入表依赖 **mujoco.dll** + VCRUNTIME140/MSVCP140。Windows 解析 DLL 依赖
只查「该 DLL 自身目录 + 进程已注册搜索目录」→ plugin/ 里没有 mujoco.dll (MSVCP140 只在
PyQt5/Qt5/bin) → WinError 126; PyInstaller 的 ctypes 钩子 (`PyInstaller/loader/pyimod03_ctypes.py`
会 patch ctypes.CDLL) 把底层 OSError 包装成上面那句 —— **真正的 cause 在 `e.__cause__`**,
所以报错处务必把 `__cause__` 打出来, 否则永远查不出缺哪个 DLL。

**零 Windows 取证手法**:
1. 下载已发布 exe → `python -m PyInstaller.utils.cliutils.archive_viewer -r -b App.exe > list.txt`,
   grep `mujoco` 看 `mujoco\mujoco.dll` / `mujoco\plugin\actuator.dll` 各自在哪一级;
2. `pip download --no-deps --only-binary=:all: --platform win_amd64 --python-version 3.12 --implementation cp -d /tmp/w mujoco==<ver>`
   拿到 Windows wheel (就是 zip) → `pefile` 读插件 DLL 的导入表, 知道它缺谁。

**修法** = `--runtime-hook pyi_rth_mujoco_dlls.py` (钩子在主脚本前跑, 早于 import mujoco)。**别硬编码一套依赖就以为完事** —— 实测同一个 bug 在 CI runner 上底层原因是
`OSError [WinError 1114] A dynamic link library (DLL) initialization routine failed`(DLL 找到了但初始化失败),
在真机上可能是 `WinError 126`。所以钩子要**逐级修 + 每级真 `ctypes.CDLL` 实测 + 修不动显式降级**, 并把结论写进环境变量留证:
① 注册 `_MEIPASS` / `_MEIPASS/mujoco` / `_MEIPASS/mujoco/plugin` 到 DLL 搜索目录 + PATH
   (注意 ctypes.CDLL 走 LOAD_WITH_ALTERED_SEARCH_PATH, 别只靠 AddDllDirectory);
② 仍加载不了 → 把 `mujoco.dll` 复制进 `plugin/` (让插件目录自足 —— 依赖解析必然包含 DLL 自身目录);
③ 再把 `VCRUNTIME140* / MSVCP140*` 复制进去;
④ 仍失败 → 把该插件改名 `*.dll.zmax-off` **显式停用**(mujoco 的 `_load_all_bundled_plugins` 只扫
   `.dll/.so/.dylib`, 改名后就不会去 load) —— **前提是先证明产品不用引擎插件**: `grep -r "<plugin" 全库 + metaworld/assets` 命中 0。
非 Windows / 非 frozen 直接 return。模板见 `templates/pyi_rth_mujoco_dlls.py`。

**发版前必须真验 (只查"文件在不在包里"抓不到这个 bug)**: GUI 加 `--engine-selftest` 入口
(放入口脚本顶部、Qt 导入之前; `--windowed` 下 sys.stdout/stderr 为 None → 结果写 json + 退出码,
且 `traceback.print_exc()` 会再抛 AttributeError 把真错误盖掉 → 有 stderr 才打印), CI 里真跑
`ZMAX_SELFTEST_OUT=... ./App.exe --engine-selftest` → 真 import mujoco/metaworld + 建模型 + 步进;
失败即 fail 发版。再加一个 A/B job (`workflow_dispatch` 开关) 构建**不装钩子**的基线并断言它必须崩
→ 证明根因 + 证明核验步骤"有牙" (不是永远绿的装饰)。渲染只记录不判失败 (CI runner 无显示)。

## Common CI failures & fixes

| Symptom | Root cause | Fix |
|---------|-----------|-----|
| Checkout fails: `invalid path ':Zone.Identifier'` | Windows ADS files in repo | `git rm --cached` + `*:Zone.Identifier` in `.gitignore` |
| Release upload: "Resource not accessible" | Missing `permissions: contents: write` | Add permissions block to job |
| Release upload: skipped on workflow_dispatch | `if: startsWith(github.ref, 'refs/tags/v')` doesn't match branches | Add `|| github.event_name == 'workflow_dispatch'` |
| workflow_dispatch uses wrong tag | `github.ref_name` is branch name, not tag input | Use dedicated `Determine release tag` step |
| .exe crashes: `ModuleNotFoundError: grpc` | Missing grpcio in pip install | Add `grpcio protobuf` to deps |
| .exe crashes: `ModuleNotFoundError: torch` | torch not bundled | Wrap in try/except with `_TORCH_AVAILABLE` flag |
| .exe crashes: `AttributeError: 'HomeWidget' has no '_check_updates'` | Button calls main window method directly | Use `pyqtSignal` pattern instead |
| .exe 点「运行」即崩: `Failed to load dynlib/dll '...\mujoco\plugin\actuator.dll' ... not found when the application was frozen` | 插件目录里没有它依赖的 `mujoco.dll`(在上一级 `mujoco/`) + VC 运行时 | `--runtime-hook pyi_rth_mujoco_dlls.py` (把依赖复制进 `mujoco/plugin/` 做自足目录) + CI 冻结核验 `App.exe --engine-selftest`; 报错处打印 `e.__cause__` |
| .exe crashes at startup: `FileNotFoundError [WinError 3] ...\AppData\Local\data` | PyInstaller **onefile** exe cwd ≠ repo (unpacked temp/AppData); relative-path `os.listdir("data")` throws | Guard EVERY filesystem probe with `os.path.exists/isdir` before listdir; build paths from an absolute `_repo_root()` (frozen-aware), never bare relative names; probe-only code must degrade to empty list on missing dirs |

### Qt GUI Patterns

#### KPI Label Style Preference

The user prefers **concise labels without system-level suffixes**. When displaying KPI/metric labels:

- `"定位精度"` — YES
- `"定位精度·Sys-11"` — NO (rejected as redundant)
- `"推理延迟"` — YES  
- `"推理延迟·Sys-11"` — NO
- `"控制周期"` — YES
- `"控制周期·Sys-0"` — NO

The system name suffix is implicit from the context/color coding — the text label alone is sufficient.

#### Child Widget → Parent Method Signal

**Problem**: Button in `HomeWidget._hero()` calls `self._check_updates()` → `AttributeError` because the method lives on `QMainWindow`, not the child.

**Pattern**: Define `pyqtSignal(str)` on child, emit with string target, connect in parent.

```python
class HomeWidget(QWidget):
    module_clicked = pyqtSignal(str)

    def _hero(self):
        # RIGHT: emit signal, parent handles
        btn.clicked.connect(lambda: self.module_clicked.emit("check_updates"))
        # WRONG: self._check_updates()  ← AttributeError

class MainWindow(QMainWindow):
    def _build(self):
        self.home = HomeWidget()
        self.home.module_clicked.connect(self._on_nav)

    def _on_nav(self, target):
        if target == "check_updates":
            self._check_updates()
            return
```

Existing pattern in same codebase (already used by module cards):
```python
card.clicked.connect(self.module_clicked.emit)
ver_btn.clicked.connect(lambda: self.module_clicked.emit("version"))
```

**When to use**: Any button in a child widget that triggers a main-window-scope action.

### YAML / CI Pitfalls

- **'on:' YAML gotcha**: PyYAML parses `on:` as boolean `True`. Quote it: `"on":` for local testing. GitHub's parser handles it correctly either way.
- **Release upload needs `contents: write` permission**: Without it the GITHUB_TOKEN can't upload assets.

## Delivery Speed Preference

This user values speed over ceremony. Guidelines:
- "迭代不超2轮" — limit iterations, deliver working artifact quickly
- "加速" / "用最快的速度" — skip verification scripts, push directly, wait for CI, deliver download link
- "回忆昨天，保存数据，清理垃圾，小迭代远程控制台" — batch independent tasks, execute in parallel when possible
- After a build-breaking fix, one verification pass is sufficient. Multiple rounds of verification create friction, not confidence.
