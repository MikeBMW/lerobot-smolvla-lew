# 2026-08-06: 推理视频窗口修复 + 执行队列误匹配 + row_bg 尺寸同步 (commits 6acd11ca/ea918c94/5aa4ecc8/2bea7f48)

老倪反馈: "5模型对比的视频打开后不动, 要保持5个都打开在最前面不被遮挡, 看着做对比"

## 🐛 视频打开不动的根因: 帧目录不匹配 (最易踩)
InferenceVideoDialog._load_frames 旧逻辑只找 `reports/rollout_<policy>/`。
但 rollout 生成脚本可输出任意目录 (--out), 昨晚产物实际在 `rollout_peg_<p>` (peg-insert 场景)
和 `rollout_final_<p>`。→ 加载不到帧 → 视频区显示"无数据"不动。

修复: 多候选目录按优先级 (simulink_scope.py _load_frames + simulink_module.py on_infer_video 的 have 检查):
```python
for cand in (f"rollout_final_{policy}", f"rollout_peg_{policy}", f"rollout_{policy}"):
    frames = sorted(glob.glob(os.path.join(root, "reports", cand, "frame_*.png")))
    if frames: found = frames; break
```
规律: **任何读 reports/rollout_* 的地方都要多候选**; 新场景 (peg) 生成到新目录时,
旧代码读默认目录必然"数据丢失"。

## 🖥 5 窗口置顶不被遮挡
- InferenceVideoDialog.__init__: `self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)`
- 入口 _show_nonmodal 已统一置顶 (WindowStaysOnTopHint + raise_ + activateWindow), 所以
  对话框本身置顶即可; 单窗口内 5 个视频框并排 (一个窗口, 不是 5 个独立窗口)。

## 📐 5 视频同屏对比 — 必须网格布局, 不能 HBox 并排 (2bea7f48, 老倪: "第一个能打开, 第二个呢?")
**坑**: 5 个视频框 `lab.setFixedSize(400, 300)` 放 QHBoxLayout 并排 = 2000px 宽,
但窗口 `setMinimumSize(min(1280, 240+n*220), 640)` 只有 1280px → **后 4 个视频框被挤出
屏幕外**, 用户只看到第一个 → "第一个能打开, 第二个呢?"。固定尺寸 + 并排 = 溢出被裁剪。
**修复**:
```python
cols = 3 if n > 3 else n          # 5 模型 → 3+2 两行
vid_grid = QGridLayout()          # 替换 QHBoxLayout (需 from PyQt5.QtWidgets import QGridLayout)
for i, (policy, name, color) in enumerate(self.POLICIES):
    r, c = divmod(i, cols)
    vid_grid.addLayout(box, r, c)
# 视频框: 不 setFixedSize! 用 setMinimumSize(240, 180) 让布局自适应缩放
lab.setMinimumSize(240, 180)
# 窗口: 5 模型 min 1500x700 (不是 1280)
w_min = 1280 if n <= 3 else 1500
h_min = 640 if n <= 3 else 700
```
规律: **多个固定尺寸大 widget 放一行必超窗口被裁剪 — 要么网格布局要么自适应尺寸**。

## 🎯 双击单个视频节点 → 自动升级全模型对比 (2bea7f48)
老倪: 双击「🎥 视频对比 · ACT」只开 1 个模型没意义, 要 5 个同时一起打开做对比。
on_infer_video 里 policy 参数不再"只放该模型", 而是**先探测画布 → 全模型列表, 单模型
只在不在全模型列表时兜底**:
```python
names = " ".join(n.get("name", "") for n in self.nodes)
if "VLA-Touch" in names or "AWE" in names:
    policies = InferenceVideoDialog.POLICIES_5
else:
    policies = InferenceVideoDialog.POLICIES
if policy and not any(p == policy for p, _, _ in policies):
    policies = [(policy, ...)]   # 异常兜底才单模型
```

## 🔁 循环播放 (看着做对比)
_tick 原逻辑播完 stop → 改循环: 末尾时 `self.cur_idx = 0` 而不是 `self._timer.stop()`。
⚠️ 测试时注意: 第一次 tick 渲染末尾帧后 cur_idx 才 == n, 第二次 tick 才归零 — 断言要 tick 两次。

## 🕐 每模型元信息副标题: 生成时间 + 动作幅度 (c148c4c6)
老倪反馈: "视频可以加载上次训练的, 但得显示上次训练生成的时间, 也不知道是什么时候生成的。
现在感觉视频都差不多啊, 都没拿起来" → 每个视频框标题下加小字元信息:
```python
self._meta_labels = {}          # policy → QLabel (init 时与 video_labels 同建)
self.frame_meta = {}            # policy → "MM-DD HH:MM · 动作σ=0.464"
# _load_frames 里每个 policy 填充:
mtime = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(frames[0])))
a = np.load(os.path.join(os.path.dirname(frames[0]), "actions.npy"))
astd = f"动作σ={float(np.asarray(a).std()):.3f}"   # actions.npy 与帧同目录
self.frame_meta[p] = f"{mtime} · {astd}"
self._meta_labels[p].setText(self.frame_meta[p])
```
**动作σ是"机械臂是否真在动"的量化指标** (见 metaworld-sim-eval 速查表):
- 专家数据 std≈0.3-0.7; 训练后 rollout std>0.3 = 在动; std<0.1 = 数据压扁或推理路径错
- 视频对比"都差不多/没拿起来"先看各模型动作σ差异, 别直接怀疑视频渲染

## ♻ 重新生成统一昨晚验证过的方向正确配置
_run_rollouts 子进程参数:
```python
["--policy", policy, "--steps", "60", "--task", "peg-insert-side-v3",
 "--camera", "corner2", "--rotate-ccw",
 "--out", os.path.join(root, "reports", f"rollout_final_{policy}")]
```
peg-insert 插销场景 corner2 视角 + 逆时针旋转90° → 插孔可见方向正立 (昨晚飞书端验证结论)。
⚠️ 2026-08-06 晚最终确认: corner2 视角实际需 **k=2 (旋转180°)** 方向才正 (rollout_video.py
rotate_ccw 分支 `np.rot90(rgb, k=2)`, commit b73ed5a7)。

## 🐛 ▶运行执行队列关键字误匹配 (6acd11ca, 训练到第3个停了)
_canvas_stage_nodes 按 NODE_RUN_ACTIONS 关键字匹配环节节点, 两个误匹配坑:
1. 🎥 推理效果对比 含"推理" → 误匹配 on_infer → 混进五模型对比队列排最后 → 阻塞后续训练
2. ☑ 训练开关 含"训练" → 误匹配 on_train → CICD 主控台 ▶运行 第一个环节变成开关 (打乱语义)
修复: 循环里排除观察/控制节点:
```python
if n.get("params", {}).get("video"): continue   # 视频显示: 手动双击, 不自动跑
if n.get("type") == "train_gate": continue       # 控制标志, 非执行环节
```
另外 _speed 排序字典要含全部 policy (act/smolvla/smolvla_lew/vla_touch/awe_zflow),
新模型忘加 → key=9 排最后不致命但顺序错。
验证: 五模型队列恰 5 stage 无视频/开关; CICD 首个环节是 ACT 训练。

## 🐛 row_bg 背景行节点两个渲染坑
1. **黑色块** (ea918c94): add_node 创建 SimNodeItem 时 w=150/h=50 固定,
   _draw_model_rows 里改 node["w"]/["h"] 后**必须同步 item.w/item.h**:
   ```python
   it.w = int(w); it.h = row_h - 16   # 不同步 → boundingRect 仍 150×50,
                                      # paint 却画 2000×214 → 渲染成深色小块 = "黑色块"
   ```
   再加 `it.setZValue(1)` (低于节点 z=10: 点空白命中背景行, 点节点命中节点)。
2. **大字叠字** (fa38c188/86d85fce): 左侧模型名大字 (24px bold 含🎨前缀, 宽120-180px)
   与每行第一列节点 (x≥120) 重叠 → 视觉"重复/叠字"。
   修复: row_bg 起点 `x0 = base_x - 140` (大字绝对右界 = x0+8+126 < 120 零重叠),
   大字去 emoji 前缀 + 15px bold + 最长名 (SmolVLA+LEW) '+' 拆两行。
   验证: 5 模型名 15px bold 拆行后每行 ≤126px; 大字绝对右界 < 节点 x=120。
   ⚠️ 计算时用实际 base_x (120): `x0 = base_x - 140` 得 -20, 不是注释想当然的 -130/-140。

## 🎨 BlockParamsDialog 颜色下拉
bg/bg_color/color 参数 → QComboBox 12 预设色 (● 色块+名称), _apply 用
`w.currentData() or w.currentText()` 取 itemData — 否则取到带 label 的显示文本。
