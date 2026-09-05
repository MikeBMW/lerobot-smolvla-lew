"""YOLO 3D 感知链 (2026-08-12 老倪: 从 tools/ 移入 policies/ 统一管理)

感知前端: 相机图像 → YOLO 检测 光模块/hole/hand → 2D→3D 解算 → 39D state
与 Model Zoo 各策略同层级: 策略(动作) / 感知(状态输入) 统一在 policies/ 下。

模块:
- train_yolo.py         YOLO 检测训练 (ultralytics, 3类)
- yolo_state_aligner.py 2D→3D 解算 + state 对齐 (YoloStateAligner)
- gen_yolo_data.py      仿真自动标注生成 (零人工标注)
"""
from .yolo_state_aligner import YoloStateAligner

__all__ = ["YoloStateAligner"]
