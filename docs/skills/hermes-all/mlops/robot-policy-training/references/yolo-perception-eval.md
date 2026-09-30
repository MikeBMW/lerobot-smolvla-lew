# YOLO 感知链 + 评估管道修复细节 (2026-08-07/08 实测)

## YOLO 感知链 (仿真=真机同构)
- 链路: 相机图像 → YOLO 检测 (hand/peg/hole 2D框) → 2D→3D 反投影 → 对齐 39D state → 策略输入
- 训练数据 `--yolo` 模式: YOLO 检测替换 39D 对应段 (模拟真机感知, 不白给坐标)
- **训练/评估必须同构**: 训练用 YOLO 检测 state → 评估也必须用 YOLO 检测 state, 否则假 0%

## ultralytics BGR 坑 (最重要)
- `model.predict(rgb_array)` 对 RGB numpy 数组返回 0 框!
- 必须 `cv2.cvtColor(img, cv2.COLOR_RGB2BGR)` 再 predict
- 文件路径 predict 正常; 内存数组必须 BGR
- 内存 BGR ~10ms/帧 vs 临时文件 ~1s/帧 (慢 100 倍)

## 相机 2D→3D 反投影
```python
from scipy.spatial.transform import Rotation
q = env.model.cam_quat[cam_id]
R = Rotation.from_quat(q).as_matrix()
fwd, right, up = -R[:,2], R[:,0], R[:,1]
f = (H/2) / np.tan(np.radians(fovy)/2)
ndc_x, ndc_y = (u-W/2)/f, (v-H/2)/f
dir_ = fwd + ndc_x*right + ndc_y*up
t = (plane_z - cam_pos[2]) / dir_[2]
pt = cam_pos + t*dir_  # 高度用真实值(仿真)或深度(真机), 假设误差大
```
- peg 画面中心 ±4cm 精度; hole 边缘误差大用插入点推断
- 39D 段位: hand=[0:3], peg=[18:21], hole=[36:39] (实测 _get_obs)

## 评估管道 3 大坑 (全部导致假 0%)
1. **逐维归一化**: SmolVLA preprocessor 是逐维 39 mean/std; ACT 旧版是标量需广播
   - 读 `policy_preprocessor_step_3_normalizer_processor.safetensors` 的 observation.state.mean/std
   - 不能共用一份 stats — `_load_stats(policy_name)` 按模型映射
2. **SmolVLA 图像 64×64**: config siglip_image_size=64, 喂 128 视觉编码全错; ACT 128
3. **AWE/VLA-Touch 反归一化**: diffusion 输出归一化空间, 必须 act*std+mean (stats 键 a_mean/a_std)
   - 无 _cond 的模型走 else 分支同样要反归一化

## 45D 目标条件化
- state 加 [peg-hand, hole-peg] 相对向量 (39+6=45D)
- 评估时现场补 6 维: env obs 39D → 模型 45D
- 数据 info.json 同步 state shape [45] + codebase_version v3.0

## 数据生成器坑
- 官方专家假设标准起点, 远移后状态机失效 → --far/--grab-only 用多阶段专家
- lifted 判断用 peg 升高 (peg_z > peg_z0+0.04), 不能用手的 z (初始就高 → 永远 True → 跳过抓取)
- grasp_pt 每步重新取 peg 位置 (循环内 peg 会动)
- 丢弃轨迹后 episode_index 重编号 0..N-1 + 重建 info.json
