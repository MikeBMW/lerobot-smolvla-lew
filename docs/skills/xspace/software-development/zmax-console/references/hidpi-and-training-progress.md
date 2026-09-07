# 高分屏 DPI + 训练进度条 + Model Zoo 配置表语义 (2026-08-25)

## 1. 高分屏字体小 — 根本原因与诊断

本机屏幕是 **3200x2000 @ 236 DPI** 高分屏（13.5" 笔记本），但 X 系统 DPI 是 **96**（默认值未设对）。
→ Qt 按 96 DPI 渲染 1pt，实际物理字高只有应有的 96/236 ≈ **40%**。
所以用户反复抱怨"字体小"、堆字号到 60pt 还嫌小。

诊断命令：
```bash
DISPLAY=:0 xrandr --current | grep connected   # 看物理分辨率 (3200x2000)
DISPLAY=:0 xdpyinfo | grep resolution          # 看 X DPI (96 = 错误, 实际应 ~236)
```

**用户明确拒绝 200% 缩放**（`QT_SCALE_FACTOR=2`）：窗口/布局整体放大 2 倍后过大、超出屏幕。
最终方案 = **100% 缩放 + 手动放大字号**（终端 log_text Consolas 60、log_box 32pt、其余文字 18-20px）。

⚠️ 教训：用户说"字体小"先查屏幕 DPI（xrandr/xdpyinfo），别盲目堆字号。字号堆到 60pt 还嫌小 = 一定是 DPI 问题，不是字号问题。启动脚本 launch_studio.sh 里不要默认加 QT_SCALE_FACTOR（用户要 100%）。

## 2. 本地训练进度条一直 0%

根因：本地训练（lerobot_train 走 simulink `_line_hook`）只解析 loss 更新曲线，**从不更新进度条**；
进度条 `progress_bar` 只在远程训练 `_poll_remote_progress` 里 `_update_progress` 更新。

修复（4 处，已 commit cc0c596e）：
1. simulink_module.py 类级加 `progress_signal = pyqtSignal(int)`
2. `_line_hook` 里解析 `Training: (\d+)%` 或 `step:(\d+)` → `self.progress_signal.emit(pct)`
   （总步数 = `int(steps) if steps else 3000`）
3. studio.py `_init_simulink` 里 `sim.progress_signal.connect(self.model_engine._update_progress)`
4. on_train 训练启动 emit(0)，训练结束 emit(100 if rc==0 else 0)

⚠️ worker 线程直接操作 QProgressBar 会 SIGSEGV → 必须用 signal 跨线程（见 memory 崩溃铁律）。
进度解析只在下次训练生效，不追溯已结束的训练。

## 3. Model Zoo 配置表语义 (ZOO_SPEC)

- **"模型宽度" = 向量宽度**（隐藏层维度 512/1024/256），不是模型规模。
  YOLO 检测是 CNN 检测器，无此概念 → 填 "—"（不适用），不是 yolov8s/yolov8n。
- **"架构"栏**表达网络结构，风格"主干→输出"：ACT=ResNet18→Transformer，
  YOLO=YOLOv8n·CSPDarknet(C2f)→PAN-FPN→解耦头（要表达 CNN 层结构，不能只写"检测器"）。
- YOLO 检测**实际模型是 yolov8n**（train_yolo.py 默认 `--model yolov8n.pt`），
  `_train_yolo_detector` 调用时不传 --model 走默认。曾硬编码写 yolov8s 是显示/实际不一致的 bug。
- 铁律：表格/日志里显示的值必须和实际训练模型一致（老倪工程真实性零容忍）。
