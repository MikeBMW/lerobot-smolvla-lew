# npz → LeRobotDataset v3.0 转换 + MetaWorld joint 采集 (2026-08-02 实测)

## 一、重大坑: meta 模板会掩盖真实数据维度

`data/metaworld_act`、`data/closed_loop` 的 `meta/info.json` 是从 pusht 拷贝的模板
(state 2D / image 96x96 / 25650 帧)。LeRobotDataset 按 **meta 的 features** 定义读数据,
训练/评估实际加载的是 pusht parquet, 本地 npz (metaworld 4D / Orin 7D) 从未被使用!

铁律: **训练后必须检查模型 `input_features` 验证数据真实维度**:
```python
json.load(open('<ckpt>/pretrained_model/config.json'))["input_features"]
# 若 state shape == [2] 且 image [96,96,3] → 训练用的是 pusht 模板数据, 不是你的 npz!
```
此前"metaworld 训练"(v111/finetune/s1) 全部实为 pusht 训练, 靠这个检查才暴露。

## 二、npz → LeRobotDataset v3.0 转换器 (tools/npz_to_lerobot.py)

npz (observations CHW float 0-1 + states + actions) → 标准 v3.0 目录:
`meta/info.json + stats.json + tasks.parquet + episodes/parquet + data/chunk-000/file-000.parquet + videos/observation.image/chunk-000/file-000.mp4`

### 视频必须用 PyAV h264, 不能 cv2.mp4v
- cv2 VideoWriter(mp4v) 无关键帧索引 → LeRobotDataset 视频解码失败
  (症状: `ds[i]` 报 `ensor_input(decoder, frame_indices=...)` 截断错误)
- 正确: `av.open(path, 'w')` + `container.add_stream('h264', fps)` + `yuv420p`
  (PyAV 已随 lerobot 依赖安装)

### 所有 episode 共用一个视频文件 (file_index=0)
- LeRobotDataset 的视频 timestamp 语义是**全局累计**: 每个 episode 的
  `videos/observation.image/from_timestamp` 从 0 开始累加 (ep2 从 6.67s 起)
- 若每 episode 单独视频文件且 timestamp 全局累计 → 在文件内找帧超界
  (`Invalid frame index=149 must be less than 100`)
- 正确结构 (pusht 模板同款): **全部帧写进一个 file-000.mp4**,
  episodes 表每行 `videos/observation.image/file_index: 0` + from/to_timestamp 全局累计
- 转换器代码: `np.savez_compressed` 的 npz → `tools/npz_to_lerobot.py --npz X --out Y --task T --fps 30 --episode-frames 100`

### episodes parquet schema 细节
- `tasks` 列必须是 `pa.list_(pa.string())` (不是 string) — 否则 pyarrow 报 "Expected bytes, got a 'list' object"
- stats 列按前缀推导类型 (min/max/mean/std → float64, count → int64, done/success → bool_)

## 三、MetaWorld 3.x joint 采集 (tools/collect_metaworld_joint.py)

### API 关键点 (metaworld 3.1.1)
- 任务名用 **v3** 后缀: `metaworld.MT1('reach-v3')` (`reach-v2` 报 "not a V3 environment")
- **必须 `env.set_task(mt.train_tasks[0])`** — 否则 `AssertionError: _last_rand_vec is None`
- **Gymnasium API**: `obs, info = env.reset()`, `obs, rew, term, trunc, info = env.step(a)`
  (reset 返回 tuple, 不是裸 obs)
- 默认 action 是 4D 末端控制 (dx,dy,dz+gripper); **无 joint action 模式** — 用默认动作驱动仿真,
  记录数据时 action 用**关节速度差分** (delta qpos)
- `env.data.qpos` 是 16D (Sawyer 7 关节 + 物体/夹爪等自由度); 前 7 个是关节角
- 夹爪开合: `np.linalg.norm(rightclaw.xpos - leftclaw.xpos) / 0.1` clip 0-1

### 维度对齐铁律 (与 Orin 6 关节匹配)
- Orin 真实包 state 是 **6D** (`n_joint=6`, 无夹爪维度) — 本地旧 7D (6关节+夹爪) 是错误定义
- joint 采集 state 取 `qpos[0:6]` (6D), **不要**拼夹爪 (7D 会导致 Stage3 权重迁移维度不匹配
  `mat1 and mat2 shapes cannot be multiplied (8x6 and 7x256)`)
- action = 6D 关节速度差分; 图像 offscreen render 64x64 (对齐 Orin)

### 渲染环境
- 直接终端跑需 `DISPLAY=:0` (WSLg); execute_code 沙箱无 DISPLAY →
  `GLFWError: (65550) X11: The DISPLAY environment variable is missing` → subprocess 传
  `env={**os.environ, "DISPLAY": ":0", "MUJOCO_GL": "egl"}`
- 无头渲染用 `mujoco.Renderer(model, w, h)` 即 EGL offscreen, 可用

## 四、数据包 action 恒等 bug (fix_orin_action.py)

Orin 采集端把当前关节状态当 action 记录 → 数据包 `action == observation.state` → 训练学恒等映射。

- 检测: `np.allclose(actions, states, atol=1e-3)` (或各轴均值完全相同)
- 修复: action → 关节速度差分 `delta[i] = state[i+1] - state[i]`, 末帧用前向差
  (`delta[-1] = states[-1] - states[-2]` — 注意 np.diff 是后向差, 末帧缺失)
- 已集成: `_ensure_training_data` 拉包后自动调 `fix_frames`; 独立工具 `tools/fix_orin_action.py --check pkg.json`
- 检查数据是否真实: 各轴动作均值/状态帧间变化完全相同 = 占位/合成数据

## 五、验证脚本坑 (ad-hoc 验证纪律)

- GUI 验证用系统 python3 (有 PyQt5), 训练/数据集验证用 `.venv/bin/python` (有 lerobot/torch)
  — 混用会 ModuleNotFoundError 或 PyQt5 缺失
- metaworld 采集 subprocess 必须传 DISPLAY/MUJOCO_GL 环境 (见上)
- 验证脚本写 PIPELINE_STATE.json 会污染真实状态 → 用 monkeypatch 或临时路径,
  跑完恢复真实状态 (S1 真实 ckpt 丢失会导致 Stage2 兜底回退旧模型)
