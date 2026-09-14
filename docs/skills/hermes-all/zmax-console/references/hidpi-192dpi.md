# 192 DPI 高分屏 — UI 像素尺寸验证坑 (2026-08-22 v2.4.0)

## 现象
控制台首页 12 张功能模块卡片, 白色大字标题 + 灰色小字描述"显示不全"(被裁)。

## 根因
U盘环境 = Ubuntu 24.04 live, Xorg 3200x2000 高分屏:
- `xdpyinfo | grep resolution` → 报 96x96 DPI (X 报的是错的, 不反映真实)
- 真实: `QApplication([]).primaryScreen().logicalDotsPerInch()` → **192.0** (physicalDotsPerInch 189)
- `QT_SCALE_FACTOR=1.25` → `app.devicePixelRatio() == 1.25`

192 DPI 下字体渲染尺寸 = 96 DPI 的 **2 倍**:
- 14pt bold 标题: fontMetrics.height=42, sizeHint(h)=54 (offscreen 96DPI 下只有 34)
- 9pt 描述: 单行 35, 两行 70, 长 URL 三行 91 (offscreen 下两行 40)

而 `QT_QPA_PLATFORM=offscreen` 平台默认 **96 DPI**, 测出的 sizeHint 只有真实一半 →
硬编码的 `setMinimumHeight(34/40)` + `setFixedHeight(300)` 在真实屏幕全部不够, 标题/描述被裁。

## 铁律
**验证 UI 像素尺寸必须用真实 DISPLAY=:0 跑, offscreen 只用于测逻辑/拓扑/字符串/对象存在。**

## 诊断命令
```bash
DISPLAY=:0 xdpyinfo | grep -E 'dimensions|resolution'
DISPLAY=:0 QT_SCALE_FACTOR=1.25 <gui-venv>/bin/python -c "
from PyQt5.QtWidgets import QApplication
app=QApplication([])
print('dpr=',app.devicePixelRatio())
s=app.primaryScreen()
print('logicalDPI=',s.logicalDotsPerInch(),'physicalDPI=',s.physicalDotsPerInch(),'size=',s.size())
"
```

## 修法 (v2.4.0)
弃硬编码像素尺寸, 改内容自适应 (任何 DPI 都对):
1. 标题/描述 QLabel: `setWordWrap(True)`, **不设死 setMinimumHeight**
2. 卡片 QFrame: `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)`, **弃 setFixedHeight** (同行 QHBoxLayout 自动等高)

验证脚本模板:
```python
import sys
sys.path.insert(0, "/home/ubuntu/lerobot-smolvla-lew/tools/gui")
import studio
from PyQt5.QtWidgets import QApplication, QLabel
app = QApplication([])
home = studio.HomeWidget(); home.show(); home.resize(1400, 900); app.processEvents()
fails = []
for c in home.findChildren(studio.ModuleCard):
    for w in c.findChildren(QLabel):
        if w.height() < w.sizeHint().height() - 2:
            fails.append(f"{c.mid}:{w.text()[:12]} 高{w.height()}<需{w.sizeHint().height()}")
print("✅" if not fails else "❌ " + "; ".join(fails))
```
运行: `DISPLAY=:0 QT_SCALE_FACTOR=1.25 <gui-venv>/bin/python verify.py`
