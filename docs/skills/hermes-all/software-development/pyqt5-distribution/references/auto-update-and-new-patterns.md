# Session 2026-07-30: New Patterns

## 1. Self-Updating PyInstaller Windows App

**Pattern**: Detect new GitHub Release → download .exe → replace on restart.

### Architecture

```
update_checker.py
├── check_latest()         — GitHub Releases API (timeout=8)
├── download_update()      — stream download with progress callback
├── check_in_background()  — threading, 5s startup delay
└── CURRENT_VERSION        — hardcoded, bumped per release
```

### Workflow

1. App starts → `QTimer.singleShot(5000, self._auto_check_update)`
2. Background thread hits `api.github.com/repos/{owner}/{repo}/releases/latest`
3. Compares `tag_name` with `CURRENT_VERSION`
4. If newer: status bar shows "📢 发现新版本 v1.0.6 — 关于 → 检查更新"

### Manual upgrade flow

**关于 → 🔄 检查更新** or home page **⬆ 升级** button:

1. `check_latest()` fetches latest release info
2. Three-button `QMessageBox`: **⬇ 下载并升级** / **🌐 打开下载页** / **稍后**
3. On "下载并升级":
   - `download_update()` streams 68MB .exe to `%TEMP%/zmax_update/Z-MAX_Console_new.exe`
   - Creates `upgrade.bat` that waits 2s, copies new.exe over old.exe, launches it, self-deletes
   - Opens the temp dir in Explorer so user can run the batch file

### Key considerations

- **PyInstaller --onefile**: Can't replace a running .exe on Windows. Need batch script trick.
- **GitHub API rate limit**: 60 req/hr unauthenticated. Use `timeout=5` for background check.
- **Network failure**: Background check silently swallows exceptions.
- **Version source**: `update_checker.CURRENT_VERSION` — bump manually with each release tag.

### Code structure

```python
# update_checker.py
CURRENT_VERSION = "v1.0.5"
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"

def check_latest(timeout=8):
    """Returns {version, download_url, release_url, published, body} or None"""

def download_update(download_url, save_path, progress_callback=None):
    """Streams .exe to local path. Returns bool."""

def check_in_background(callback):
    """Thread target: checks on 5s delay, calls callback if new version found"""
```

---

## 2. PPT Instruction Engine

**Pattern**: User writes commands as PPT slides → app parses → drives console actions.

### Supported verbs

| Verb | Action | Example |
|------|--------|---------|
| CREATE_FILE | Write document to 静界/ | `CREATE_FILE: 静界/01-培训/Z700F指南.md` |
| RUN_CMD | Execute shell command | `RUN_CMD: lerobot-train --config ...` |
| TRAIN_MODEL | Queue training task | `TRAIN_MODEL: SmolVLA v2` |
| GIT_COMMIT | Commit + push to GitHub | `GIT_COMMIT: 训练日志` |
| DEPLOY | SCP to ECS | `DEPLOY: 同步到上线服务器` |
| EVAL_MODEL | Run evaluation | `EVAL_MODEL: benchmark` |
| UPDATE_CONFIG | Modify config | `UPDATE_CONFIG: 训练参数` |

### PPT structure (per slide)

- **Title**: `VERB: Instruction Name` (e.g. `CREATE_FILE: 操作指南.md`)
- **Body**: Parameters (JSON or key=value lines)
- **Speaker notes**: Status tracking (optional)

Menu entry: **🎯 PPT 指令控制** → 生成模板 / 解析执行 / 打开目录

---

## 3. GitHub API Dynamic Doc Discovery

**Alternative to hardcoded manifest**: List files via Contents API at sync time.

```python
def _list_remote():
    """Walk GitHub Contents API, return [(rel_path, name, ext), ...]"""
    excludes = {"source", "skills", "archive", "memory"}
    url = f"api.github.com/repos/{owner}/{repo}/contents/docs"
    # Recurse; filter to (.md, .pptx, .docx, .pdf)
```

Benefits:
- No manifest drift between code and remote
- New files added to GitHub automatically appear on next sync
- Excludes non-user dirs (source/, archive/, etc.)

Pitfall: GitHub API rate limiting (60/hr unauthenticated). Acceptable for manual sync; background auto-sync needs token.

---

## 4. Chinese Directory Names on Windows

Works fine: `os.path.join(exe_dir, "静界")` — Python/os handle UTF-8 paths correctly.
`QUrl.fromLocalFile()` also handles them. No special encoding needed.

---

## 5. Zone.Identifier Full Cleanup Recipe

```bash
# Find all ADS files
git ls-files | grep ':Zone.Identifier'

# Remove from index
git rm --cached "./full/path:Zone.Identifier"

# Delete physical files
rm "./path:Zone.Identifier"

# Prevent recurrence in .gitignore
echo '*:Zone.Identifier' >> .gitignore
```

---

## 6. PyQt5 Child→Parent Signal Pattern

**Problem**: A button in a child `QWidget` (e.g. `HomeWidget._hero()`) needs to call a method on the main window. Direct `self._method()` fails with:

```
AttributeError: 'HomeWidget' object has no attribute '_check_updates'
```

**Root cause**: The method lives on the parent `QMainWindow`, not the child widget.

**Pattern**: Define a `pyqtSignal` on the child widget, emit with a string target, connect in the parent.

```python
class HomeWidget(QWidget):
    module_clicked = pyqtSignal(str)          # <-- signal on child

    def _hero(self):
        btn = QPushButton("⬆ 升级")
        # RIGHT: emit signal, let parent handle
        btn.clicked.connect(lambda: self.module_clicked.emit("check_updates"))
        # WRONG: self._check_updates()  ← AttributeError

class MainWindow(QMainWindow):
    def _build(self):
        self.home = HomeWidget()
        self.home.module_clicked.connect(self._on_nav)   # <-- parent connects

    def _on_nav(self, target):
        if target == "check_updates":
            self._check_updates()                        # <-- actual method
            return
        # ... normal navigation / tab switching
```

**Why it works**: The main window creates `HomeWidget` and connects the signal. The button emits a string id. `_on_nav` dispatches based on the string. Decoupled, no tight binding.

**Existing pattern in same codebase** (already used by module cards):
```python
# module grid cards → emit module id
card.clicked.connect(self.module_clicked.emit)

# version sync button → emit "version"
ver_btn.clicked.connect(lambda: self.module_clicked.emit("version"))
```

**When to use**: Any button in a child widget that triggers a main-window-scope action (navigation, update, sync, settings, deploy).

---

## 7. PPT Marker Convention (Agent-Triggered Slides)

**Pattern**: User places a specific marker in the top-right corner of a PPT slide → agent detects and acts on that slide.

| Marker | Meaning | Action |
|--------|---------|--------|
| `▶ 静` | Draw architecture | Add System 2→1→0 three-layer diagram using PPT native shapes |
| `▶ 指令` | Execute as instruction | Parse via ppt_engine and run |

### Drawing architecture with python-pptx

Use native PPT shapes (rounded rects, connectors, text boxes) — NOT images:

```python
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
import lxml.etree as etree

prs = Presentation("deck.pptx")
slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout

# Dark background
slide.background.fill.solid()
slide.background.fill.fore_color.rgb = RGBColor(0x06, 0x08, 0x0D)

# Rounded rect card
card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, w, h)
card.fill.solid(); card.fill.fore_color.rgb = RGBColor(0x0D, 0x11, 0x17)
card.line.color.rgb = accent_color; card.line.width = Pt(1)
card.adjustments[0] = 0.05

# Connector arrow with triangle tail end
conn = slide.shapes.add_connector(1, x1, y1, x2, y2)
conn.line.color.rgb = color; conn.line.width = Pt(2)
# Arrowhead via XML element manipulation
ln = conn._element.find('{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
if ln is None:
    ln = etree.SubElement(conn._element,
        '{http://schemas.openxmlformats.org/drawingml/2006/main}ln')
tail = etree.SubElement(ln,
    '{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd')
tail.set('type', 'triangle'); tail.set('w', 'med'); tail.set('len', 'med')
```

**Three-column layout pattern** (Z-MAX example):
- Three equal-width boxes: purple (#A371F7) for cloud, blue (#58A6FF) for edge, green (#3FB950) for hardware
- Each has accent color bar at top + alternating row items inside
- Downward connector arrows between columns
- Right-side data-feedback box in orange (#F7A90B)
- Bottom color legend with small filled rects + text labels

### Marker shape (top-right corner)

```python
marker = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
    Emu(10500000), Emu(100000), Emu(1500000), Emu(500000),
    None, RGBColor(0xF7, 0xA9, 0x0B))  # orange border
marker.line.width = Pt(2)
marker.fill.solid()
marker.fill.fore_color.rgb = RGBColor(0x06, 0x08, 0x0D)  # dark fill

txBox = slide.shapes.add_textbox(Emu(10500000), Emu(100000),
    Emu(1500000), Emu(500000))
p = txBox.text_frame.paragraphs[0]
p.text = "▶ 静"
p.font.size = Pt(16); p.font.color.rgb = RGBColor(0xF7, 0xA9, 0x0B)
p.font.bold = True
```

**Key technique**: `conn._element` (not `conn.line._element`). Connectors in python-pptx have no `line._element` attribute; use the connector's direct XML element instead.

---

## 8. Version Bump Checklist

Don't force-push the same tag — the auto-updater compares `tag_name` and won't detect a change.

```bash
# 1. Bump version in ALL three files:
#    tools/gui/update_checker.py → CURRENT_VERSION
#    tools/gui/version_sync.py   → zmax_ver
#    tools/gui/docs_sync.py      → "version" meta

# 2. Commit + new tag (NEVER force-push the old one)
git add -A && git commit -m "release: Z-MAX v1.0.x — <feature>"
git tag v1.0.x                    # <-- NEW tag number each time
git push origin main --tags

# 3. Wait for CI → .exe appears on Releases page
```

**Why force-pushing fails**: The Release asset URL stays the same (old `.exe`), and the auto-updater sees the same `tag_name` and thinks nothing changed. Each release needs a unique semantic version.

---

## Consolidation Note

**4 overlapping skills detected** (`windows-app-deployment`, `pyqt5-distribution`, `desktop-app-packaging`, `zmax-console`). All cover PyQt5→Windows .exe via CI. Recommend curator consolidation into one umbrella (`pyqt5-distribution` is most complete). The other 3 can reference it or be absorbed.
