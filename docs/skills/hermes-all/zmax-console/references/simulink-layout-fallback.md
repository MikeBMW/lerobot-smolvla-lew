# Simulink 画布节点布局 — 兜底跑飞 pitfall (2026-08-07)

## 症状
老倪: "Interpolant 和 未来决策交叉注意力 node 怎么在显示区域右侧那么远"
→ 节点出现在画布右侧 x=6000~8000px, 显示区完全看不到, 要拖很久滚动条。

## 根因
simulink_module.py 模板 = (name, node_specs, link_specs, layout_grid)。
`load_reference_app()` 按 layout 网格给节点排位 (base 120,80; 列距 200; 行距 230)。
**node_specs 里名字不在 layout 网格中的节点 → 静默兜底单行**:

```python
xy = next((p for p in cands if p not in used), None)
if xy is None:
    xy = (base_x + i * 200, base_y)   # i = specs 索引!
```

兜底位置 x = 120 + i*200, 全部挤在顶部一行 (y=80)。
五模型对比 specs 41 节点: 索引 25 的 🌉 Interpolant → x=6620, 索引 30 的 🔀 未来决策交叉注意力 → x=7920。

触发经过: 往 specs 加了新节点 (🎯 YOLO 目标检测 idx2 / 📐 2D→3D 解算 idx3 / 🔤 Encoder idx7 /
🔡 Decoder idx8) 却没同步 layout 网格 → 6 节点漏出, 最远两个就是老倪看到的。

## 修复
1. **重写 layout 网格覆盖全部 specs 节点**: 感知链独占首行
   (📦数据→🎯YOLO开关→🎯YOLO检测→📐2D→3D→🔌StateAdapter), 每模型一行, 按拓扑顺序排
   (VLA-Touch 行: …ActionHead→🌉Interpolant→🚀训练; AWE 行: …🌊zFlow→🔀交叉注意力→ActionHead→训练)。
2. **列距 260→200** (load_reference_app 内三处 260 全改 200): 10 列网格总宽 ~1920px,
   与旧 8 列 × 260 相当, 不会更宽。共享节点多行占位只取第一个未用位置, 其余行留空对齐。
3. 旧 layout 中无效占位名 (specs 里不存在的节点名, 如 MLP/专家行残留) 可顺手删, 无损失。

## 验证 (改布局必做)
AST 提取模板数据、重放分配算法、断言零兜底 —— `scripts/verify-simulink-layout.py`。
关键: 模板数据虽是模块级常量, 但 import 模块会拉起 PyQt5 副作用 → 用 ast 解析, 不 import。
五模型应报: 41节点 9行 兜底=0 maxX=1920 maxY=1920。全部 11 模板 0 兜底才算过。

## 守则
- **给模板加节点 = specs 加条目 + layout 网格同步加条目, 缺一不可**。
- 节点名必须与 specs 里的 name 逐字一致 (含 emoji), 否则匹配不上照样兜底。
- 改完布局重启 GUI 看效果 (ZMAX_AUTO_RUN=1 自动加载五模型对比)。

## 背景行 row_bg 与网格同步 (2026-08-07 追加: 老倪 "背景跟node没对齐")
### 症状
加了感知链首行后: ACT 背景带盖在 YOLO 感知行上, AWE 行没有背景带 —— 整体错位一行。
### 根因
背景行由独立函数 `_draw_model_rows(row_names, row_h=230, col_w=200, base_x=120, base_y=80, n_cols=10)`
绘制, 位置 y0 = base_y + r*230 - 20, **r 从 0 开始按 row_names 顺序排**。layout 网格加了首行
(感知链) 后所有模型行下移一行, 但 row_names 还是 5 个模型名 → 背景行从 y=80 首行开始,
每行都压到错位的模型行上 (ACT 背景→感知行, SmolVLA 背景→ACT 行, …, AWE 无背景)。
### 修复
1. `_draw_model_rows` 参数与 layout 网格一致: **col_w/n_cols 必须等于布局列距/列数**
   (260→200 改列距时这里不同步会超宽; n_cols=8→10)。
2. 调用处 row_names 加首行名, 与 layout 首行对应:
   `_draw_model_rows(["YOLO 3D 检测", "ACT", "SmolVLA", "SmolVLA+LEW", "VLA-Touch", "AWE"])`。
3. palette 加新行名颜色 (如 "YOLO 3D 检测": "#3a5a7a"), 缺色默认 #26418f 会串色。
### 验证
`scripts/verify-simulink-layout.py` 已含背景行检查: 每行背景 y0 与节点行 y 对齐
(背景 y0+20 == base_y + r*row_h) + 背景右界覆盖该行最右节点 (bg_right = (base_x-140) +
(base_x + n_cols*col_w + 120) - (base_x-140) ≥ max(node_x)+150) + palette 覆盖全部行名。

## 附: WSL 重启后恢复控制台 (老倪: "你刚才怎么又退出了")
先查根因再恢复, 别背锅也别瞎猜:
```
uptime -s; systemctl --user status hermes-gateway | head -3   # 时间吻合 = WSL 整体重启
```
WSL 重启会杀光: 本会话 + 控制台 + auto_loop 训练。恢复 = 重启控制台:
```
cd ~/lerobot-smolvla-lew/tools/gui && ZMAX_AUTO_RUN=1 DISPLAY=:0 bash run_studio.sh  # background
```
(pkill -f studio.py 可停旧实例; "Unknown property cursor" QSS 警告无害。)

## 附2: 命令行启动必须用 /usr/bin/python3 (2026-08-07 实测)
- **`.venv/bin/python` 没有 PyQt5** (`ModuleNotFoundError: No module named 'PyQt5'`) — venv 是训练环境, GUI 依赖在系统 python。**直接命令行启动用 `/usr/bin/python3`**:
  `cd ~/lerobot-smolvla-lew && DISPLAY=:0 ZMAX_AUTO_RUN=1 /usr/bin/python3 tools/gui/studio.py` (background)
- **PATH 里 `python3` 可能是 hermes venv** (无 PyQt5) — 别用裸 `python3`, 显式 `/usr/bin/python3`。检查: `/usr/bin/python3 -c "import PyQt5"` 应 OK
- **ZMAX_AUTO_RUN=1 钩子**: 启动后 2.5s 自动 `stack.setCurrentWidget(simulink)` → `open_compare5()` → `start_sim()` — 老倪要看画布运行就用它; 它内部 `_qmsg_yes = lambda *a,**k: True` 自动点确认框
- **窗口置顶** (老倪: "控制台放到桌面前端"): `win.setWindowFlag(Qt.WindowStaysOnTopHint, True)` + `win.show()` + `win.raise_()` + `win.activateWindow()` — 已写入 studio.py main()
- **`ImportError: cannot import name 'SimulinkModule'`** = simulink_module.py 被截断 (见 metaworld-sim-eval "编辑大 GUI 文件铁律"), 先 `git show HEAD~3:tools/gui/simulink_module.py > 文件` 恢复再启动
- **窗口看不到但进程活着**: 查 `ls /tmp/.X11-unix/` (X0 在) + `ps aux | grep -iE 'wayland|Xwayland'` (WSLg 服务) — 0 个 = WSLg 没起, GUI 无处显示; 这是 WSL 侧问题, 重启 WSL 或等 WSLg 自愈, 控制台进程本身没坏
