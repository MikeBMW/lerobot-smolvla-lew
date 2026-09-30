# Offscreen GUI 验证脚本 — 正确执行方式

## ⚠️ 必须用系统 python3, 别用 execute_code 的 sys.executable (2026-08-05 实测)

`execute_code` 里 `subprocess.run([sys.executable, path])` 用的是 **Hermes venv python (无 PyQt5)**
→ GUI 验证脚本 import PyQt5 失败 exit 1, 误判为代码坏 (本会话误判过一次)。

正解:
- execute_code 里跑验证脚本: `subprocess.run(["python3", path], ...)`
- 或直接 terminal 前台跑: `timeout 50 python3 /tmp/hermes-verify-*.py`

判别: PyQt5/requests/torch 类依赖在**系统 python3** 或项目 `.venv`, 不在 hermes venv。

## 标准验证脚本模板 (offscreen)

```python
import os, sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, '/home/xspace/lerobot-smolvla-lew/tools/gui')
from PyQt5.QtWidgets import QApplication
app = QApplication([])
import simulink_module as sm
# offscreen 下跳过所有模态确认框 (exec_ 会阻塞挂死)
sm.SimulinkModule._qmsg = lambda self, *a, **k: None
sm.SimulinkModule._qmsg_yes = lambda self, *a, **k: True
```

- 脚本写 /tmp/hermes-verify-*.py 跑完即删
- 过滤 stderr 噪音: `grep -vE "Unknown property|could not parse|qt.qpa|propagateSizeHints|raise()"`
- 拿退出码: `${PIPESTATUS[0]}` (管道后 $? 是 grep 的)
- `scene.render(p, target=..., source=...)` 的 target 必须 QRectF, 传 QRect 报 TypeError
- 模态 QMessageBox.exec_() 在 offscreen 下会阻塞超时 — 必须 monkeypatch _qmsg/_qmsg_yes

## 排查顺序: palette 对 ≠ 渲染对

offscreen 断言 palette 深色 ≠ 用户看到深色。先渲染采样像素:
```python
from PyQt5.QtGui import QPixmap, QPainter, QImage
pm = QPixmap(w.size()); pm.fill()
p = QPainter(pm); w.render(p); p.end()
img = QImage(pm.toImage())  # 或直接 pm.toImage().pixelColor(x,y).name()
```
渲染出浅色但 palette 深色 → 有 paint/drawBackground 硬编码盖底 (本会话: SimCanvas.drawBackground 硬编码 #f0f2f5)。
