# YoloStateAligner 漏传 depth_weights → 静默回退写死 z (2026-09-03)

## 触发场景
GUI 画布 ▶运行/单步 YOLO 感知采样,VSCode 断点停在
`yolo_state_aligner.py detect_3d` 第 118 行「回退: 写死 z 平面」分支
(plane_z = z_map.get(cls, 0.1) 那段)。

## 根因 (证据链)
- 断点停回退分支 = `depth_m is None` = `depth_map is None` = **深度模型未加载**,
  不是检测代码问题。
- `_yolo_ensure_aligner` (tools/gui/node_logic.py) 构造
  `YoloStateAligner(检测权重, env0)` 时**漏传 depth_weights** →
  `__init__` 里 `depth_model = YOLO(depth_weights) if depth_weights else None` →
  None → detect_3d 的 `if self.depth_model is not None:` 跳过 →
  **无任何报错**走写死 z 回退。
- detect_3d 内部 `except Exception: depth_map = None` 吞异常也会造成同现象
  (cuda tensor 未 detach().cpu() 是另一实例, 已修)。

## 构造点盘点 (grep `YoloStateAligner(` 逐个核对)
| 调用点 | depth_weights |
|--------|--------------|
| tools/gen_insert_video.py (L180) | ✅ 传 |
| tools/train_full_pipeline.py (L131) | ✅ 传 |
| tools/gui/node_logic.py `_yolo_ensure_aligner` | ❌ **曾漏 (2026-09-03 已修)** |
| yolo_state_aligner.py main() CLI demo | 不传 (可接受) |

## 断点诊断 (VSCode 两变量一眼定位)
- `self.depth_model` → None = 构造漏传/权重路径无效
- `depth_map` → None = 深度模型未加载或推理异常被吞

## 分支判据 (一票判定走哪条, 不需看断点)
- 深度反投影: z **偏离**写死 plane_z (hand 0.155 / peg 0.03 / hole 0.129)。
  实测修后: hole 偏离 5.6mm / hand 8.4mm / peg 20.9mm。
- 写死回退: z **恒等** plane_z (t 解在平面上) → 偏离必 = 0。
- 修前所有 3D 的 z 恒等 plane_z; 修后全偏离 → 铁证深度分支生效。

## 修复模板 (与 gen_insert_video.py:36 同款)
```python
_d_cands = ["outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt",  # GPU自动校准版 scale 0.978/0.885
            "outputs/yolo_peg_depth/peg_depth_v1/weights/best.pt",     # 旧 CPU 版已作废
            "outputs/yolo_peg_depth/peg_depth_smoke/weights/best.pt"]
_dw = next((c for c in _d_cands if os.path.isfile(os.path.join(_REPO_ROOT, c))), None)
aligner = YoloStateAligner(w, env0,
                           depth_weights=(os.path.join(_REPO_ROOT, _dw) if _dw else None))
# 日志必打深度路径: 有 → "· 深度 outputs/..." 一目了然;
# 无 → "⚠️ 无深度权重 → detect_3d 走写死 z 回退" 明示, 不静默
```
深度权重位置: `outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt` (本机存在)。
scale 配套: hand 0.885 / peg+hole 0.978 (`DEPTH_SCALE` / `DEPTH_SCALE_HAND` 环境变量,
yolo_state_aligner.py 默认值已固化, 勿传 1.0 或旧 1.685/1.566)。

## 单例坑
node_logic `_YOLO_ALIGNER` 是模块级单例 — 一旦以旧构造 (无深度) 加载,
改完代码**必须重启 studio.py** (GUI 铁律: 改完代码必重启), 热重载不重建单例。
重启后重新 ▶ 运行, 断点应改停在深度反投影分支 (depth_m>0.1 成立处, ~L111)。

## 冒烟验证命令 (独立进程, 无需 GUI)
```bash
cd tools/gui && DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python -c "
import sys, numpy as np
sys.path.insert(0, '.')
import node_logic as nl
a = nl._yolo_ensure_aligner(None)
print('depth_model:', 'OK' if a.depth_model is not None else 'NONE')
det3d = a.detect_3d(a.env.render())
for cls, pt in det3d.items():
    plane = {'hand':0.155,'peg':0.03,'hole':0.129}[cls]
    print(f'{cls}: z={pt[2]:.4f} 偏离平面 {(abs(pt[2]-plane))*1000:.1f}mm')
# 偏离全 >0 → 深度分支; 有 =0 → 仍回退
"
```
