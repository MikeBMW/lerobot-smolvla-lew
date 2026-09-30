# 统一执行入口 + node_logic 坏引用 + 环境安装坑 (2026-08-30)

## 统一执行入口 `_run_node_single` (单步 ⏭ 与右键「运行节点」共用)
老倪 2026-08-30: "重新统一单步运行和鼠标右键运行节点的功能, 包括UI显示, 高亮提示等"。
落地 (commit 86d44554): 新增 `SimulinkModule._run_node_single(node, label=None, keep_active=True)`:
- **分派规则 (优先级)**:
  1. 环节节点 (名字匹配 NODE_RUN_ACTIONS 任一 kw) → `_run_node_stage(node, fn, label or kw)` — worker 异步, running青→success绿/error红 (含 execute_node_logic)
  2. `params.run_env` 数据层节点 → `_run_node_stage(node, lambda: self._run_env_wrap(node), label or "数据层")` — `_run_env_wrap` 调 on_run_env 并包装成 (ok, summary) 给 CICDWorker (on_infer_rollout 返回 None 不能直接进 CICDWorker!)
  3. 其他节点 → `self._highlight_node(node, ms=2500)` + `_sim_node(node, keep_active=keep_active)`
- **keep_active 语义**: 单步=True (金色保持=当前步位置); 右键运行=False (运行完即绿)
- **防重入**: 开头检查 `self._worker.isRunning()` → `_busy_hint()`
- **入口改造**: `step_sim()` 拓扑序推进 + 调 `_run_node_single` (label=f"单步 {i}/{n}", keep_active=True); 右键菜单 "运行节点" (simulink_module.py `_show_node_menu` 的 `chosen == a_run`) 从 `on_node_activated` 改 `_run_node_single(item.node, label="右键运行", keep_active=False)`。`_run_node_stage` 日志文案 "⏳ 双击运行" → "⏳ 运行" (统一)。
- 双击 (on_node_activated) 语义不变 (配置/切换/参数框)。

## ⚠️ 单步假绿 bug (异步 worker 启动后不能立即标 success)
`_sim_node` 里 `execute_node_logic` 对环节节点 (node_train → on_train 启动 worker) 会立即返回,
原代码随后直接标 `success` — **后台真训练在跑, 节点却显示"完成"** (假状态, 老倪红线)。
统一后环节节点走 `_run_node_stage` 异步状态流转, 不再假绿。教训: 凡 execute_node_logic / on_xxx 可能启动
worker 的路径, 节点状态必须交给 worker 的 finished_ok→_done 回调, 不能同步标绿。

## node_logic.py 坏引用系统性检查 (假激活扫描)
node_logic.py 里 `module._toggle_source_node(...)` 等方法**从未在 SimulinkModule 存在** (git 历史确认
v1.5.0 引入时就是错的), 异常被 `_sim_node` 的 `except Exception: pass` 吞掉 → 节点"运行成功"但动作没发生
(数据源假激活 / YOLO 开关状态从不落地)。快速全量检查:
```python
import re
src = open('tools/gui/node_logic.py', encoding='utf-8').read()
calls = set(re.findall(r'module\.([a-zA-Z_][a-zA-Z0-9_]*)\(', src))
missing = sorted(c for c in calls if not hasattr(simulink_module.SimulinkModule, c))
```
本会话揪出 2 处: `_toggle_source_node` (→ `_toggle_source_ctx`), `_set_yolo_gate_ctx` (→ `_toggle_yolo_gate_ctx`)。
修复模式参照 `_toggle_train_gate_ctx`: 按节点名在 `self.nodes` 找 node dict → 调真实方法。修完跑
offscreen 断言 active/yolo_enabled 真实翻转。

## match_node 最长匹配坑: 注册词必须与模板节点名子串一致
`_reg("yolo_gate", ["YOLO开关"], ...)` 匹配不到模板节点 "🎯 YOLO 感知开关" (中间隔"感知"不是子串),
被 `_reg("ss_yolo", ["YOLO", ...])` 的 "YOLO" 抢先 → 开关逻辑从不执行 (画布节点执行的是别人)。
修: 注册词补全模板实际名字 "YOLO 感知开关" (最长匹配优先, 不影响 ss_yolo 其他节点)。
教训: 新增节点类型时, `_reg` 的 matches 必须含模板节点名中能唯一锚定的完整子串; 排查"节点逻辑不生效"
先 `match_node(name)` 看 key 落到谁。

## source 参数双语义: 数据源标识 vs 代码路径
数据源/数据层节点 `params.source = "metaworld"` 是**数据源标识**, 不是文件路径 — `open_node_source` 拿它
拼 `repo_root/source` 报"文件不存在"误导 (2026-08-30 老倪反馈)。修: 路径不存在时先查
`node_logic.match_node(name)` + `get_node_location(key)`, 有映射则弹提示 "source=... 是数据源标识,
运行逻辑在 node_logic.py:行号 · 函数名, 用右键「查看/编辑节点逻辑」"; 无映射才报文件不存在。
`run_env` 数据源节点 (source + run_env 都有) 在 on_node_activated 里 run_env 分支**先于** source 分支
→ 双击/运行 = 按模式训练/推理, 不是切换激活。

## 右键菜单黑屏二分诊断法
老倪报"右键菜单全黑" → 用 **menu.grab() (Qt 离屏渲染, 绕过 X 显示) vs QScreen.grabWindow (屏幕合成)**
二分: 本会话实测三种 QMenu 样式 (默认/深色/浅色) qt_grab 全部正常 (浅色237/深色41), 屏幕 0.5s 内正常上屏
→ 结论是环境/时序, 不是代码 bug。当前 Xorg 环境菜单正常, 2026-08-12 VcXsrv 深色 QSS 黑屏坑仍有效。
⚠️ 验证脚本 monkeypatch QMenu.exec_ 后 restore 不干净会污染后续模态循环 (QTimer 不触发) — 渲染验证单独跑。
真实右键复现: xdotool 坐标 = 窗口内容区偏移 (X11 frame vs 内容, mutter 下差 ~100px) + 栈上其他全屏窗口
(对话框/VSCode)会拦截点击 — 先 `xwininfo -root -tree` 看栈序, 必要时 windowmove 移开遮挡窗口。

## pip/uv 装 metaworld 系列卡死处理 (2026-08-30 实测)
- `uv pip install metaworld` 卡死: 0% CPU、无网络连接、90 分钟不动 → kill 换路。
- `pip install metaworld==3.0.0` (aliyun 源) 也卡: resolver 解析依赖树时挂起; `--no-deps` 也卡 (下载后)。
- **正解**: wheel 已在 /tmp/pip-unpack-* 下完 → 校验 `unzip -t` (pip 下的可能截断损坏) → 损坏则 curl
  files.pythonhosted.org 断点续传 (`curl -C -`, sha256 比对) → `--no-deps` 安装或直接 unzip 解包进
  site-packages → 逐个 import 补缺: glfw / imageio / scipy / PyOpenGL (aliyun 源快)。
- 本机环境: ~/lerobot-venv (uv 建的, 无 pip 模块, `python -m ensurepip` 后才有) + metaworld 3.1.1 +
  mujoco 3.3.0。requirements-macos.txt 锁 metaworld==3.0.0 (3.0.0 wheel 下载不稳未装成)。
- gen_insert_video 12/12 seed 卡转移/下降 = 模型与 metaworld 物理不匹配 (contact_head 预测 0.30-0.41
  徘徊达不到 0.5 阈值; 降阈值 0.35 会误进转移但 peg 抓空) — 诊断脚本: 加载模型 → 状态机逐步打印
  hand/peg/hole/contact, 卡在哪一步看哪段坐标。本机可用 left_right 模型被磁盘红线清光, 要出视频需新模型。
