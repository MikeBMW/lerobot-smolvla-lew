# 字体/字号放大 — 老倪偏好 + 关键位置 (2026-08-25)

## 触发
老倪反馈 "字体太小看不清" / "还得放大" / "放大2倍至少" — 这是 192 DPI 高分屏下小字号渲染过小的表现
(姊妹篇: hidpi-192dpi.md 讲控件"被裁", 本篇讲字号"太小")。

## 老倪偏好 (铁律)
- **字号往大调、一次到位**。连续三轮反馈 (太小→还得放大→放大2倍) 每轮都是"没改够"。
  新写 GUI 控件字号起点 **≥13px (QSS font-size) / ≥12pt (QFont)**, 别再用 9-11px 小字号 — 老倪看到小字必反馈。
- 终端/日志字要**特别大** (22pt/28 是老倪认可档位), 不是 11-14 那种常规大小。

## 老倪认可的字号基准 (2026-08-25 三轮后落定)
| 控件 | 位置 | 基准值 |
|------|------|--------|
| 底部日志框 log_box | simulink_module.py 4111 | `font-size:22pt` (QSS) |
| 训练日志终端 log_text | studio.py 3717 | `QFont("Consolas", 28)` |
| 配置通道 zoo_table (Model Zoo 对比表) | studio.py 4196 起 | QSS `font-size:14px` + 表头 QFont 13 / 参数名 12 |
| cfg_std_table (标准参数表) | studio.py 7501 起 | 同上 14px / 13 / 12 |
| 训练开关 checkbox | studio.py 3552 | 14px |
| 容器管理三模式按钮 | studio.py 2933 | 15px |

## 全局放大法 (一轮批量, 别逐个手改)
正则映射, 两个文件 (studio.py + simulink_module.py):
```python
import re
def scale_px(m):
    n = int(m.group(1)); mp = {8:11, 9:12, 10:13, 11:14, 12:15}
    return f"font-size:{mp[n]}px" if n in mp else m.group(0)
def scale_qfont(m):  # 只放大极小值 6-9
    n = int(m.group(2)); mp = {6:10, 7:10, 8:11, 9:12}
    return f'QFont("{m.group(1)}", {mp[n]}' if n in mp else m.group(0)
txt = re.sub(r'font-size:\s*(\d+)px', scale_px, txt)
txt = re.sub(r'QFont\("([^"]+)",\s*(\d+)', scale_qfont, txt)
```
- 日志终端类控件 (`log_box`/`log_text`) 别用 px 映射, 单独用 **font-size pt / QFont pointSize** 调 (日志字要大)。
- 表格 QFont 有两处几乎相同的代码 (zoo_table 用 `t.setItem`, cfg_std_table 用 `zoo_t.setItem`) —
  patch/替换时 old_string 必须带 `t.setItem`/`zoo_t.setItem` 锚点区分, 否则命中 2 处报 "Found 2 matches"。
- 改完 `gui-venv311/bin/python -m py_compile` 验语法 (patch 的 new_string 缩进丢失会出 IndentationError, 已实测踩过)。

## 重启铁律
改完字号**必须重启 studio.py** 才生效 (老倪反复强调"改完必重启"):
```bash
pkill -f "[g]ui-venv311/bin/python studio.py"; sleep 3   # 方括号技巧防自杀
cd ~/lerobot-smolvla-lew/tools/gui && DISPLAY=:0 bash launch_studio.sh  # background=true
```
launch_studio.sh 已有实例则只激活不重启 → 必须先 pkill。重启后 `pgrep -af "[g]ui-venv311/bin/python studio.py"` 拿新 pid 汇报。

## 复盘
三轮字体反馈的根因 = 每轮只改了"用户点名的那个控件" (终端/表格/开关), 没做**全局**放大。
正确做法: 用户第一次说"字体太小"就直接全局正则放大 + 把终端字号调到 22pt/28 档位, 一次到位。
