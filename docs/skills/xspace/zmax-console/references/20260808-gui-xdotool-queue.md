# GUI 真实按钮操作 (xdotool) + Model Zoo 训练队列 + 详细终端打印 — 2026-08-08

老倪铁律迭代：**"你要操作窗口按钮，不能只在后台执行"**——改代码/后台执行不算数，要看到真实 GUI 按钮被点击。

## xdotool 操作 WSLg GUI (真实点击)

```bash
sudo apt-get install -y xdotool
DISPLAY=:0 xdotool search --onlyvisible "" | while read w; do
  DISPLAY=:0 xdotool getwindowname $w 2>/dev/null   # 找窗口 ID (如 "XSpace Studio — Z-MAX v1.7.0 - [画布]")
done
DISPLAY=:0 xdotool windowactivate <winid>
DISPLAY=:0 xdotool getwindowgeometry <winid>        # Position + Geometry (布局估算基准)
DISPLAY=:0 xdotool mousemove <x> <y> click 1        # 盲点点击
DISPLAY=:0 xdotool getwindowname <winid>            # 点击后查标题确认切页成功 (迭代)
```

- 主窗口 = SystemSidebar (三层卡 SYS2/SYS1/SYS0) + QStackedWidget —— 无 QTabWidget 快捷键，只能坐标点
- **盲点迭代法**：点 (x,y) → 查窗口标题（页名在标题里，如 "[画布]" → "[模型引擎]"）→ 未中调整坐标重试；左侧导航栏 x 在窗口左缘 +40 附近，三个 SYS 卡纵向分布
- 找不到按钮坐标时：从代码布局推理（grep studio.py 布局顺序 + 控件几何）而非瞎点

## 训练按钮 → Simulink Model Zoo 完整训练队列 (7 模型串行)

老倪：**"点击训练按钮，就是训练 model zoo 的 simulink 模型"** + **"完整训练 model zoo 的模型"**。

双向注入：`simulink.set_model_engine(model_engine)`（simulink 训练走引擎）+ `model_engine.set_simulink(simulink)`（训练按钮 → simulink on_train）。

```python
ZOO_POLICIES = ["act", "smolvla", "smolvla_lew", "vla_touch", "awe_zflow", "expert_mlp", "expert_policy"]

def _start_training(self):            # 训练按钮入口
    if self._simulink is not None:
        if self._zoo_queue: return    # 队列已在跑
        self._zoo_queue = list(self.ZOO_POLICIES)
        self._zoo_next(); return

def _zoo_next(self):                  # 串行推进
    if not self._zoo_queue:           # 队列空 → 报告 + 视频
        self._simulink.on_pdf_report(); self._simulink.on_infer_video(); return
    if pgrep lerobot_train 有进程: return   # 等当前训练完 (15s QTimer 轮询)
    pol = self._zoo_queue.pop(0)
    self._simulink.on_train(policy=pol)     # on_train 是后台线程, 不阻塞
```

- 完成检测用 `pgrep -f lerobot_train`（进程消失 = 训练结束）——QTimer 15s 轮询 `_zoo_next`
- 队列开头若已有训练在跑（pgrep 有进程）→ 不重复启动，等它完再推进
- 队列空 → `on_pdf_report()`（📄 Model Zoo 技术选型报告）+ `on_infer_video()`（🎮 视频对比）——产物落 reports/ + outputs/train/（本地训练天然落本地，无需额外同步）

## 详细终端打印 (老倪监控时)

_line_hook（simulink_module on_train 内）**不要简化**——每行完整打印：

```python
def _line_hook(ln):
    ln_s = ln.rstrip()[:240]
    pts = self._parse_loss_curve([ln], prefer_action=True)
    if pts:
        step, loss = pts[-1]; cur_dict[step] = loss; _flush_curve()
        self.log_signal.emit(f"📈 {pname} {step}步 · loss {loss:.4f} · {ln_s}")
    else:
        self.log_signal.emit(ln_s)   # 非 loss 行也完整打印 — 老倪: 不要简化, 我在监控
```

（旧版每 10 步一行摘要被老倪否定——"终端信息要详细，不要简化"）

## 表格风格偏好

配置通道 = **宝马整车配置表风格**（https://www.bmw.com.cn 车型配置表）：类别分组行（🏗 架构 / ⚙️ 训练 / 📊 数据·输出 / 🏆 性能——横跨全宽合并单元格）+ 参数行（参数名列 + 7 模型横列）——"像选车型一样横比模型"。亮点值金色标注（✅/🏆/唯一/novae）。

## 用户纠正记录

- "不是删除 smolvla 模型列 / 停止删除smolvla"——**别删 SmolVLA 模型列**（7 模型横列保留）；老倪要删的是 **SmolVLA 专属信息块**（🧠 SmolVLA Model 标签/vlm_info——旧版专属信息，7 模型下拉已替代）
- "将配置通道…删掉 模型选择下拉"——表格展示 7 模型后右侧下拉冗余 → 删 UI，**对象保留**（`self.model_combo` 隐藏——训练逻辑读 currentText 默认 "ACT"）
- "配置通道右侧两个拖动条，删一个"——表格自身滚动条 ScrollBarAlwaysOff + 内容全高 setMinimumHeight(内容高)，外层 scroll 滚
- "删掉配置表格下面原来的参数"（Freeze SmolVLM/Action Steps/VLM Layers 等 40 处 addRow）——**删 addRow 行，控件创建保留**（self.xxx 属性——训练逻辑读值不崩）——删后 ast.parse + fresh 验证
- 功能页名改回：**"模型引擎"页名不动**（改"配置通道"后老倪让改回——"原来的模型引擎不要改"）——只有参数窗口叫"配置通道"
