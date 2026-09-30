# 高分屏字体 / DPI 缩放 (2026-08-25)

## 硬件事实
本机是 3200x2000 高分屏 (物理 344x215mm ≈ 13.5 寸, 约 **236 DPI**)，但 X 系统 DPI 错配为 **96**。
结果：Qt 按 96 DPI 渲染，1pt 实际物理大小只有应有的 **40%**，所有字体"看起来小"。

验证命令：
```bash
DISPLAY=:0 xrandr --current | grep current      # 3200x2000
DISPLAY=:0 xdpyinfo | grep resolution            # 96x96 dots per inch ← 错配根因
```

## 老倪的决策 (重要, 别重蹈覆辙)
- **GUI 必须保持 100% 缩放**。曾试 `QT_AUTO_SCREEN_SCALE_FACTOR=1 + QT_SCALE_FACTOR=2` (200%)，
  结果整个窗口/布局放大 2 倍、窗口过大，用户当场要求回退："GUI 100%就可以了，别放大"。
  → **不要再用 DPI 缩放去解决字小**，窗口会过大被否。
- 正确做法：**手动放大 QSS `font-size:Npx` / QFont pointSize**，不改 DPI 缩放。

## 终端字体的位置 + 老倪接受的最终值
- 模型引擎训练日志终端: `studio.py` ~3717 `QFont("Consolas", N)` → 最终 **42**
- Simulink 底部日志框: `simulink_module.py` ~4111 `font-size:Npt` → 最终 **32pt**
- 其他小字体(标签/按钮/训练开关 checkbox): QSS `font-size` → 最终 **18-20px**
  - 训练开关 checkbox 在 studio.py ~3552 `QCheckBox{... font-size:Npx ...}`
  - 容器管理三模式按钮 ~2933、上传/推送 ~2952/2956

## 排障教训
用户连续多轮说"字小/看不清"时，先查 `xrandr` + `xdpyinfo` 判断是否 DPI 错配，而不是无脑堆字号。
堆字号是治标，且堆到 32pt/42 用户仍可能觉得小(物理 40%)。
但注意：DPI 缩放(200%)会被否(窗口过大)，所以最终落点是"100% 缩放 + 手动放大字号"的组合。

## 改字体必重启
改 studio.py / simulink_module.py 后必须 `pkill -f "gui-venv311/bin/python studio.py"` 再
`DISPLAY=:0 bash tools/gui/launch_studio.sh` 重启才生效 (老倪反复强调)。
