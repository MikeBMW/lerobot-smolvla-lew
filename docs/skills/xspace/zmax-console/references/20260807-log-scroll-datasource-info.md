# 日志区自动滚动坑 + 数据源信息框 (2026-08-07)

## 日志区自动滚动 — 用户痛点 (老倪: "我用鼠标调整, 滚轮查信息后, 不要自动跳了, 我还没等看清就跳了")
**问题**: `_log`/`_safe_log` 无条件 `append(msg)` + `setValue(verticalScrollBar().maximum())` → 新日志一来就滚到底, 用户手动滚动查看历史时被强制拉回底部。

**修复方向 (标准 Qt 模式, 未落地 — 改代码需重启 GUI, 而重启会杀 lerobot_train 训练, 挂起等训练完)**:
```python
def _log(self, msg):
    sb = self.log_box.verticalScrollBar()
    at_bottom = sb.value() >= sb.maximum() - 40   # 用户是否在底部附近
    pos = sb.value()
    self.log_box.append(msg)                       # append 会把光标移末尾 → 视图跟随
    if at_bottom:
        sb.setValue(sb.maximum())                  # 在底部 → 跟随最新
    else:
        sb.setValue(pos)                           # 用户在看历史 → 保持不动
```
`_safe_log` (QMetaObject QueuedConnection) 同理: 先读 at_bottom (调用时当前值), 在底部才 invokeMethod setValue(maximum), 否则不设。

**注意**: 改 simulink_module.py 后 GUI 不重启不生效 (Python 模块已加载, 画布刷新也读旧类)。重启安全判定见 zmax-model-compare-report 的 pkill 精确模式节 (只有 lerobot_train 类在跑才必须等; train_yolo 等独立脚本安全)。

## 数据源节点双击 → 属性信息框 (老倪: "metaworld 数据源, 你要给出实际的数据路径, 可以双击看到具体的属性信息")
- `on_node_activated` 的 `params.get("source")` 分支从 `_toggle_source` (纯切换) 改为 `_show_source_info(node)` — 双击 = 信息框 (含"切换为激活数据源"按钮, 保留切换能力)
- `_probe_dataset(dp)`: 读 `info.json` (total_frames/total_episodes/features/fps) + 数 episodes 目录 + 递归 glob mp4/npz + os.walk 求和大小
- 候选目录: metaworld → data/metaworld_act, metaworld_mt50; orin → orin_live/orin_real_v1/orin_archive/closed_loop
- 非模态 QDialog (WindowStaysOnTopHint, 与 BlockParamsDialog 同款, WSLg 安全), 每个存在的目录一张白底卡片: 📂 实际路径 + 属性行
- 验证 (offscreen): `QT_QPA_PLATFORM=offscreen` 系统 python3 (有 PyQt5, .venv 没有) 实例化 module, `_probe_dataset("data/metaworld_act")` 返回 dict 含大小; `_show_source_info(node)` 创建不崩
- 注意 probe 用相对路径在 offscreen 下会探测错目录 (cwd=tools/gui) — 真实调用走 `os.path.join(root, p)` 绝对路径, 验证脚本别用相对路径断言具体值
