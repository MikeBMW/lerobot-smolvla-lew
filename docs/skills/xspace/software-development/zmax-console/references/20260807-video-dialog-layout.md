# 2026-08-07 视频对比窗口 + 画布布局修复 (老倪逐条打磨)

## 画布 12 列布局 (训练→仿真推理→仿真视频→Scope→PDF)
老倪最终布局: 每模型行尾 = 训练(列9) → 🎮仿真推理·模型(列10) → 🎮仿真视频·模型(列11);
评估行 = 🎮仿真推理对比(列7) + 📊对比评估Scope(列10) + 📄PDF报告(列11 最右)。
视频节点按模型对应 (ACT 行尾是 ACT 的视频, 不是横排统一视频行)。

关键机制:
- **节点 id 按 specs 顺序分配, layout 只按名字摆放** (同名节点共享 spec) →
  改 layout 行顺序不重排 id, 旧 links 全部保留, 只追加新 links
- 背景行 `_draw_model_rows(..., n_cols=12)` 单独传, 默认仍 10
- 新增节点 (如 7 个"🎮 仿真推理 · X") 追加到 specs **尾部** (id 51-57),
  links 追加 `(训练id, 推理id, "仿真推理")` + `(推理id, 视频id)` + `(推理对比34, 视频id)`
- 节点名改动要 replace_all 同步 (specs + layout); 匹配代码用子串 (`"对比评估" in name`) 兼容改名
- 训练节点 id: 11(ACT) 15(SmolVLA) 20(LEW) 26(VLA-Touch) 32(AWE) 44(MLP蒸馏) 48(专家基准);
  视频节点 id: 35-39(前5模型) 49(MLP) 50(专家)

## InferenceVideoDialog 模型名标题: 叠加视频框左下角
老倪: "每个视频的名字文本都偏上, 写到上面一行的视频里了" → 标题 QLabel 原在 box 顶部
(QVBoxLayout 第一个), 视觉飘到上面窗口 (像上面视频的说明)。
修复: QGridLayout 叠加, cap 半透明深底水印:
```python
cap = QLabel(f"■ {name}")
cap.setStyleSheet(_qss(f"color:{color};font-size:12px;font-weight:700;"
                       f"background:rgba(13,17,23,140);padding:2px 6px;border-radius:3px;"))
cap.setAttribute(Qt.WA_TransparentForMouseEvents)
stack = QGridLayout(); stack.setContentsMargins(0,0,0,0); stack.setSpacing(0)
stack.addWidget(lab, 0, 0)
stack.addWidget(cap, 0, 0, Qt.AlignLeft | Qt.AlignBottom)   # 左下角水印
box.addLayout(stack)
```
meta 时间标签 (生成时间 · 动作σ) 保留在框外上方。
画布节点同理: 视频/推理节点 (`params.get("video")`) 名字绘制改
`QRectF(6, self.h-18, self.w-12, 14)` AlignVCenter|AlignLeft (左下角) + 跳过类型标签。

## 视频对话框白屏 (lab.size()=0)
`_tick` 每 100ms `lab.setPixmap(pm.scaled(lab.size(), Qt.KeepAspectRatio, ...))` —
对话框未显示时 `lab.size()`=0 → scaled(0,0) → 白屏。
修复: 尺寸有效才缩放, 否则 `lab.setPixmap(pm)` 原图 (QLabel 自适应):
```python
if lab.size().width() > 0 and lab.size().height() > 0:
    lab.setPixmap(pm.scaled(lab.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
else:
    lab.setPixmap(pm)
```

## _check_newer_ckpt 残缺曲线误判 → 视频闪一下/再打开
对话框 `__init__` 检测到任一模型曲线 ts 比视频帧 mtime 新 60s+ → 自动重新生成 rollout。
**训练中断残留的残缺曲线** (0-50 点, ts 却新) 被误判"新 checkpoint" → 每次打开视频都触发
重生成 → 闪一下再加载。修复:
```python
if len(d.get("curve") or []) < 100:   # 1000步正常训练=200点; <100=中断残留, 不算新
    continue
```

## on_infer_video 目录映射 (expert_mlp/expert_policy 视频"没了")
`on_infer_video` 的帧检查 (have) 候选目录 = rollout_final_<p>/rollout_peg_<p>/rollout_<p>,
没有 expert 专用映射 → expert 帧找不到 → 误判无帧 → 触发重新生成 (rollout_video 不支持
expert policy) → 失败 → "视频没了"。修复: have 检查加与 dialog `_load_frames` `_dir_map` 同款映射:
```python
_dm = {"expert_mlp": ("rollout_mlp", "rollout_final_expert_mlp", "rollout_expert_mlp"),
       "expert_policy": ("rollout_expert_full", "rollout_expert", "rollout_final_expert_policy")}
```
**铁律: 触发前检查与对话框加载的候选目录必须一致** (两处都改)。

## auto_run 默认不训练 (曲线被训练链覆盖两次)
GUI 重启 `ZMAX_AUTO_RUN=1` → auto_run 触发七模型训练链 → **训练启动瞬间清空
reports/train_curve_*.json** (on_train 训练前 `os.remove(_own)` 清当前 policy 曲线) →
有效训练成果曲线全丢 (v10 报告后数据没了, 两次!)。修复: `_auto_run_compare5` 里
`start_sim` 前加 `elif os.environ.get("ZMAX_AUTO_TRAIN") == "1":` — 重启默认只加载画布,
训练由老倪手动点训练节点或 ZMAX_AUTO_TRAIN=1。曲线恢复方法见 metaworld-sim-eval
"曲线数据丢失 → 从 /tmp 训练日志秒级恢复"节。
