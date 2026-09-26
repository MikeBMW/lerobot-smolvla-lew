# 控制台 字体可读性 与 画布加载路径 (2026-09-26 老倪两次要求放大后定档)

## 1. 字体偏好 (老倪口径)
- **"字体太小, 看不清" 会连提两次** —— 第一次给了 +25% 仍被判"还是太小"。**一次给到位**: 直接上 ≈2×,
  别做小碎步; 他看的是"能不能一眼读清", 不是"有没有变大"。
- 首页「🖥 硬件资源」卡**当前定档字号**(实测 pixelSize / 行高):
  | 元素 | 原 | 现状 |
  |---|---|---|
  | 标题 `🖥 硬件资源 4060（本机）` | 14px | **34px** (行高 47) |
  | GPU / CPU / 内存 / 磁盘 / 吞吐 / 远端硬件 | 12px | **28px** (行高 39) |
  | DDS 节点列表 | 11px | **24px** |
  | 数据源行 / 时间戳 | 10~11px | **20 / 18px** |
  | 卡内两个按钮 | 11px | **20px** (padding 9×18) |
  | 卡内边距 / 行距 | 16,12 / 6 | 24,20 / 14 |
- 放大是安全的: 首页 `HomeWidget` 在 `QScrollArea(setWidgetResizable(True))` 里, 卡片变高只是让页面变长
  (实测 sizeHint 570 → 734px), 不会被裁。
- **别靠感觉报"放大了"**: 用 `tools/measure_hw_card_fonts.py`(offscreen 实例化 `studio.HardwareCard`,
  逐行打印 `font().pixelSize()` 与 `fontMetrics().height()`), 交付时把像素数贴给用户。
- 卡片里的长文本走 RichText(`setTextFormat(Qt.RichText)` + `<b>`), 字号由 QLabel 样式表统一控制, 加粗部分同步放大。

## 2. 画布加载路径必须多候选 (修「状态空间模型画布加载失败」)
根因: `simulink_module.py` 里画布/库加载只拼 `<仓库根>/flows/state_space_obs.json`, 仓库根来自 `__file__`
→ 换一棵检出(或那棵树被别的线切了分支)就找不到 → `load_flow_file` 失败 → 弹窗「状态空间模型画布加载失败」。
```python
def _flows_path(name):
    """env > 本检出 > main worktree > 默认检出 > 打包 _MEIPASS; 命中即用, 找不到返回原路径"""
```
- 用到的三处都要换成它: 画布加载(`open_state_space` 分支) · 模块库分组(`_load_state_space_library_group`)
  · 其它 flows/ 写读(`cicd_workflow.json` 等)。
- 取证: `tools/verify_canvas_load_fix.py` —— 必须包含**"仓库根=另一棵检出"**的回落场景, 否则只是证明了顺风路径。
- 启动器同源问题: `launch_studio.sh` 的 `GUI_DIR` 与 `XSpace-Studio.desktop` 的 `Exec=` 都曾硬编码某一棵树
  → 改成按脚本自身位置推仓库根 + 指向稳定 worktree(细节见 skill `systemd-boot-services`
  `references/shared-checkout-breakage.md`)。

## 3. 交付后必做
重启控制台(replace 旧实例, 不留重复进程) → 确认 `1` 个实例、启动日志 `Traceback/画布加载失败` 计数 `0`、
进程 cwd 是预期的树; 截图留档给用户(`scrot -q 88 /tmp/<名>.png`)。
