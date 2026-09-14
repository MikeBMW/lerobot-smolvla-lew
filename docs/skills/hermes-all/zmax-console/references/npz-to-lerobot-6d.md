# npz → LeRobotDataset v3.0 + 6D 关节空间统一 (2026-08-02 数据链路治本)

## 背景: 维度不匹配的根因
旧 data/metaworld_act 和 data/closed_loop 的 meta/info.json 是 **pusht 模板拷贝**
(state=2D / image=96×96 / total_frames=25650) —— 所有"metaworld/Orin 训练"实际都在训
pusht 数据! 本地 npz (metaworld 4D, Orin 7D) 从未被 LeRobotDataset 使用, 只是旁路文件。
排查证据: 模型 config.json input_features = {state:[2], image:[96,96,3]};
两个不同 root 的 LeRobotDataset len 相同 (25650) 且数据一致。

## npz_to_lerobot.py v3.0 格式硬性要求 (全部踩过)
1. **图像不在 data parquet** —— 在 videos/observation.image/chunk-000/file-000.mp4
2. **所有 episode 共用一个视频文件** (file-000.mp4 含全部帧), episodes 表每行
   `videos/observation.image/file_index` 恒 0, from/to_timestamp **全局累计**。
   多文件+局部 timestamp → `Invalid frame index=149 ... must be less than 100`
3. **视频必须 PyAV h264** (av.open + add_stream('h264') + VideoFrame.from_ndarray rgb24)。
   cv2 mp4v 无关键帧索引 → LeRobotDataset 解码崩 (`tensor_input(decoder, frame_indices=...)`)
4. tasks 列 = `pa.list_(pa.string())`; stats/count = pa.int64(); done/success = pa.bool_()
5. features 定义决定模型 input_features (图像 HWC): metaworld 4D→[4]/[128,128,3],
   Orin 6D→[6]/[64,64,3]; npz CHW 0-1 float → 视频 HWC uint8 0-255

```bash
.venv/bin/python tools/npz_to_lerobot.py --npz in.npz --out data/xxx_v2 \
    --task "任务名" --fps 30 --episode-frames 100
```

## 6D 关节空间统一 (collect_metaworld_joint.py) —— Sim2Real 维度墙推倒
metaworld 默认观测是任务空间 (plain=末端xyz+夹爪4D; with_goal 8D), 与 Orin 关节空间 6D 不匹配。
**统一方案**: state = `env.data.qpos[0:6]` (Sawyer 前6关节角, 对齐 Orin n_joint=6, 不含夹爪);
action = **关节速度差分** (qpos 逐帧差, 首帧零末帧前向差); 图像 64×64 offscreen。
- metaworld 3.x 无 joint action 模式 (action_space 恒 4D 末端控制) — 用 4D 驱动仿真,
  **记录** qpos 差分作为演示 action
- API: `MT1('reach-v3')` → `train_classes[task]()` → `set_task(mt.train_tasks[0])` →
  Gymnasium `obs, info = env.reset()`
- **headless 必须 `DISPLAY=:0 MUJOCO_GL=egl`** (无 DISPLAY → GLFWError 65550)
- **expert 脚本策略**: `metaworld.policies.sawyer_reach_v3_policy` (类名=模块名 PascalCase),
  `policy.get_action(obs)`。随机500帧 vs expert 2000帧 → Sim2Real MSE 0.0355→0.0051

## action 恒等修复 (tools/fix_orin_action.py)
Orin 采集端把当前关节状态当 action 记录 → action==state → 训练学恒等映射无效。
检测 `np.allclose(actions, states, atol=1e-3)`; 修复 = 关节速度差分;
GUI `_ensure_training_data` 拉包后自动调 `fix_frames`。数据体检: 各轴动作均值全同 = 占位数据。

## 权重迁移 CLI (预训练初始化)
- YAML `policy.path:` → `DecodingError: path not valid for ACTConfig`
- CLI `--policy.path <ckpt>` 空格 → `unrecognized arguments`
- **正确: `--policy.path=<ckpt>` (等号!)** — get_path_arg 用 parse_arg 找 `--{field}.path=`
- 维度一致 → 日志出现 `pretrained_path` 且无降级; 不一致 → forward 崩 mat1/mat2 → 自动降级从零

## 测试集评估 (eval_ds)
S2 全量评估 = 同分布过拟合假象 (MSE 0.0000/100% 无参考)。改 `test_ratio=0.2`:
idxs 只取 `range(int(n*0.8), n)` 尾部 20% 帧 (训练用前 80%, 时间分割近似无泄漏)。

## 三阶段 STAGES 数据指向
S1/S2/S3 三个 data 都要指向 6D 数据集! 只改 S1/S3 漏 S2 → S2 Sim2Real 又报
`(1x7 and 6x256)`。改完验证三阶段 LeRobotDataset 维度全一致 (6D/6D/64²)。
