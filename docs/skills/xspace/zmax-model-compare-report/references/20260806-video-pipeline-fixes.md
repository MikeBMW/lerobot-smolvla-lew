# 视频对比管道修复实录 (2026-08-06)

五模型 rollout 视频对比 GUI (InferenceVideoDialog) + rollout 推理的两轮关键修复。
适用: 老倪看「🎥 推理效果对比」窗口报"视频不动/第二个看不到/不知道啥时候生成的"。

## 1. VLA-Touch rollout x0 用上帧动作 (Interpolant 采样起点) — 动作幅度小根因

**症状**: VLA-Touch rollout 动作 std≈0.10 / max≈0.34, 视频里机械臂几乎不动, 与
SmolVLA 系 (std 0.7+) 对比悬殊。重训 500 步 loss 0.009 也没用。

**根因**: rollout 里 x0 用 `torch.randn_like(...) * 0.1` 纯噪声做插值起点, 但训练时
`q_sample(x0, x1, t)` 的 x0 = 动作轨迹前帧。推理从噪声出发, 扩散走不到动作空间。

**修复** (tools/rollout_video.py):
```python
# ❌ 坏: x0 = randn*0.1 (噪声起点 → 扩散走不到动作空间)
# ✅ 好: x0 = 上一帧动作 (与训练 q_sample 一致, 自回归)
if act_hist is not None:
    x0 = act_hist.to(dev).float()
else:
    x0 = torch.zeros((1, act_dim), dtype=torch.float32, device=dev)
pred = policy.sample(x0, cond, diffuse_steps=10)
```
**验证**: 修复后 std 0.10→0.46, max 0.34→1.05 (60 帧 rollout)。

**陷阱**: 验证 rollout 用 30 帧会误判 — 30 帧只覆盖"接近阶段" (动作本来就小,
std 0.24), 60 帧才覆盖"抓取/抬起" (std 0.46)。阈值断言必须用 60 帧 (与正式产物一致)。

## 2. 5 视频同屏对比 — "第一个能打开, 第二个呢?" 根因

**症状**: 5 模型视频窗口只看到第一个, 后面 4 个"没有"。

**根因**: 每个视频框 `lab.setFixedSize(400, 300)` 5 个并排 = 2000px, 但窗口
`setMinimumSize(min(1280, ...))` 只有 1280px → 后 4 个框被挤出屏幕外 (布局不换行)。

**修复** (simulink_scope.py InferenceVideoDialog):
- 5 模型 (n>3) → `cols = 3`, QGridLayout 3+2 两行; ≤3 模型单行
- 视频框 `setMinimumSize(240, 180)` 自适应缩放, 不再固定 400x300
- 窗口 min 尺寸: n≤3 → 1280x640; n=5 → 1500x700
- 需要 `from PyQt5.QtWidgets import QGridLayout` (容易漏)

## 3. 视频窗口元信息 — "不知道啥时候生成的"

老倪要求每个视频框副标题显示**生成时间 + 动作幅度** (对比有依据):
- 生成时间 = 第一帧 `os.path.getmtime(frames[0])`, 格式 `%m-%d %H:%M`
- 动作幅度 = 同目录 `actions.npy` 的 std: `动作σ=0.718`
- 实现: `self._meta_labels[policy]` 字典, `_load_frames` 里填充
- 需要 `import time` (simulink_scope.py 容易漏, 它在 `import json, math, os, time, glob` 里已有)

## 4. 帧加载多候选目录 — "视频加载不到昨晚的"

**症状**: 视频窗口显示"无数据", 但 reports/ 下明明有帧。

**根因**: 产物目录随迭代变化: 旧代码只找 `rollout_<p>`, 昨晚生成在
`rollout_peg_<p>` (peg 场景), 更晚在 `rollout_final_<p>` (正式版)。

**修复**: `_load_frames` 和 on_infer_video 的 `have` 检查都用候选目录优先级:
```python
for cand in (f"rollout_final_{p}", f"rollout_peg_{p}", f"rollout_{p}"):
    frames = sorted(glob.glob(os.path.join(root, "reports", cand, "frame_*.png")))
    if frames: break
```
选帧数最少的一版做同步播放 (min_len)。

## 5. 双击单个视频节点 → 自动升级全模型对比

老倪: "5个要同时一起打开, 要做对比" — 双击「🎥 视频对比 · ACT」只开 1 个没意义。
on_infer_video 改为: 画布有五模型节点 → 无论双击哪个视频节点都开 POLICIES_5 全对比;
仅当单模型不在全模型列表 (异常) 才退回单模型。

## 6. 训练步数统一 (50→10) 的联动修改清单

老倪: "改成训练10步吧, 先跑通流程"。**只改一处会混用** (有的模板 50 有的 10):
- simulink_module.py: 模板 `"steps": 50` ×17 处 + 对话框 `p.get("steps", 50)` + tooltip
- node_logic.py: 右键源码 `p.get("steps", 50)`
- train_vla_touch.py / train_awe_zflow.py: `--steps 50` docstring + `default=50`
- config_*.yaml: `steps: 50` / `steps: 2000`
- 注意排除: `000050` (checkpoint 目录名) 和 act_infer.py `n_action_steps=50` (推理参数, 不动)
- 验证: grep 残留 + offscreen 加载模板断言所有训练节点 steps==10

## 验证方法 (GUI 改动)

仓库 pytest 面向 src/lerobot, **无任何测试覆盖 tools/gui/ 的 PyQt5 文件**。
唯一可行 = offscreen 实例化 + 断言:
```python
QT_QPA_PLATFORM=offscreen
mod = type("M", (), {"_repo_root": lambda self: "/home/xspace/lerobot-smolvla-lew"})()
dlg = SS.InferenceVideoDialog(mod, policies=SS.InferenceVideoDialog.POLICIES_5)
assert len(dlg.frame_dirs) == 5          # 5 模型帧全加载
assert len(dlg._meta_labels) == 5        # 元信息标签
assert dlg.minimumSize().width() >= 1500 # 5 模型窗口
assert dlg.windowFlags() & Qt.WindowStaysOnTopHint  # 置顶
```
offscreen 限制: 窗口未 show 时 QSplitter sizes() 全 0, 不能断言"宽度恢复";
用 isHidden() 断言折叠/展开状态翻转即可。
