---
name: intact-jepa-integration
description: Use when 跑 INTACT-JEPA 官方权重/评测, 或接画布 INTACT 节点/数据源时报错.
---

# INTACT-JEPA 官方评测与画布节点集成

本机路径: `/home/ubuntu/INTACT-JEPA` (独立 `.venv` py3.10 + torch2.6+cu124, **与 gui-venv311 隔离**)。
官方能力: 零搜索 direct 控制器 (免 CEM, 每步 ~0.13ms, 5 次前向), 4 域 pusht/reacher/cube/tworoom。

## 0. ⚠️ INTACT_POLICY 指针目录必须"恰好一个 .pt" (2026-09-23 实证, 症状=trained=False 零动作)

新训产物目录常有多个权重 (weights_epoch_1.pt + weights_merged.pt)，直接拿它当 `INTACT_POLICY` →
官方加载器 `swm.wm.utils.load_pretrained(dir)` 抛
`ValueError: Ambiguous checkpoint: multiple .pt files in <dir>. Specify the file directly.`
→ worker 标 `trained=False` + `action_dim=4`(默认) → **get_action 返回零动作** (诚实标注, 不假动作)。

判"假 A/B"的最快特征: 引擎日志只有 `trained=False`, 各臂 done/steps/最小距**逐位相同**, action_dim=4 而非 8
(2026-09-23 L4 LoRA A/B 就踩了, 一度误判"新权重没提升", 实为"新权重根本没加载")。

**正确做法 (与在役 `intact_l4_current` 同构的稳定指针目录)**:
```bash
SWM=/home/ubuntu/stable-wm-cache/checkpoints
PTR=$SWM/intact_l4_<tag>
mkdir -p $PTR && cp $SWM/<训练产物目录>/config.json $PTR/config.json
ln -sfn $SWM/<训练产物目录>/weights_epoch_1.pt $PTR/weights.pt   # 目录里只留这一个 .pt 软链
ls -l $PTR    # 期望: config.json + weights.pt -> …weights_epoch_N.pt
```
自证 (秒级, 不跑整链): 用 `tools/intact_worker.py`（见下方命令）写 `{"cmd":"hello"}` 到 stdin,
期望 `{"trained": true, "dims": {"action_dim": 8, …}}`; 回 false 时**只信 reason** 字段
(Ambiguous / 权重不可达 / runtime 选错 paper↔root)。A/B 两方都必须先过这一关, 否则对比无效。

## 1. 跑官方 eval (推荐路径, 别自己拼 policy)
```bash
cd /home/ubuntu/INTACT-JEPA
export PYTHONPATH=<要注入的patch目录> \
       PATH="/home/ubuntu/INTACT-JEPA/.venv/bin:/home/ubuntu/.hermes/bin:$PATH" \
       STABLEWM_HOME=/home/ubuntu/stable-wm-cache \
       LOCAL_DATASET_DIR=/home/ubuntu/stable-wm-cache \
       MUJOCO_GL=egl PYOPENGL_PLATFORM=egl INTACT_SKIP_PREFLIGHT=1
bash scripts/eval_official.sh direct <task> <权重目录绝对路径> <seed> <num_eval>
```
- **必须绝对路径且传目录**(相对路径会被拼到 `$STABLEWM_HOME/checkpoints/` 下 → cannot resolve)
- **PATH 必须 `.venv/bin` 优先**, 否则预检选到 hermes venv → `No module named torch/h5py/pytest`
- 自拼 `WorldModelPolicy` 会炸 `'JEPA' object has no attribute 'configure'` → solver 必须是官方 `DirectSolver`
- 实测: pusht 70% (14/20, 官方报 80.22%) · **cube 100% (5/5)** · reacher 需 reacher.h5 (完整 98.9GB)

## 2. checkpoint 缺 config.json → 从形状反推
官方 tar 只含 `.pt`。`load_pretrained` 会 `instantiate(config)` ⇒ **config.json 顶层必须是模型配置**(`_target_=jepa.JEPA`), 不是整个训练配置。
用 hydra compose 从 `config/train/intact_goal.yaml` 生成, 然后按 state_dict 形状改:
| 字段 | 取值 | 依据 |
|---|---|---|
| action_encoder.input_dim | 10 (pusht/reacher) / **25 (cube)** | `patch_embed.weight` 形状 |
| intent_actor.action_dim | 同上 | `intent_actor.net.11.weight` 输出 = 2×dim |
| feature_layout | **three_slot** (576=3×192, 旧 grammar) | `intent_actor.net.0` 输入维 |
| action_emb_dim | 0 | 同上 |
动作总是 "5 步块 × DOF" 拼成 10 或 25 —— 不是 env 的动作维度。

## 3. 官方数据格式与读法 (踩过 6 个真 bug)
```python
import h5py, hdf5plugin      # ← 不 import 会 OSError: can't open directory /usr/local/lib/plugin
f = h5py.File(p, "r")
keys = list(f.keys())        # 用 list();  `k in f.keys()` / `k in grp` 判断会失效或返回数组
# ① 扁平存储(官方大文件, cube 201万帧): 用 ep_offset/ep_len 切片
if {"ep_offset","ep_len"} <= set(keys):
    off, ln = int(f["ep_offset"][e]), int(f["ep_len"][e])
    arr = np.asarray(f["pixels"][off:off+ln])       # [T,H,W,C]
# ② per-episode Group: g = f["observations"];  arr = np.asarray(g[str(ep)])
# ③ 单块 Dataset: arr = np.asarray(grp[ep])
# 取图像键: 必须**先 pixel** 再 obs — `"observation"` 是 28 维状态, 选错会当图像喂 ViT 炸
```
常见坑: `Dataset has no attribute 'keys'`(要先 `hasattr(grp,"keys")`) / `AxisError axis 1`(señal 形状) /
`expected 4, got 1`(维度没对上 → 键选错)。

## 4. 录视频 / 直跑 env (不依赖数据集)
用官方 `swm.World`, 别裸 `gym.make` (裸 env 的 obs 是 state 向量, 无像素):
```python
import stable_worldmodel as swm   # 必须在 gym.make 前 import 才会注册 swm/* env
world = swm.World("swm/OGBCube-v0", num_envs=1, image_shape=(224,224))
_, obs = world.envs.reset(seed=42)      # ★ reset 返回 (None, info) — 观测在 info 里
# to_t: 只转数值字段(dtype.kind in "fiub"), 字符串字段(id)会报错
# pixels 需 NHWC→NCHW permute; attention 前把 action 历史里的 NaN 清零
# action = model.get_action(info_dict, horizon=8) → chunk (8, action_dim), 取 chunk[:,0,:2] 喂 env
```
- OGBCube 用 **osmesa** (`MUJOCO_GL=osmesa PYOPENGL_PLATFORM=osmesa`), EGL 会 GLContext NoneType
- 合成视频: 存 PNG 序列后 `ffmpeg -framerate 8 -i f%04d.png -c:v libx264 -pix_fmt yuv420p`(imageio 缺编码器)
- patch 录帧时**输出必须走 stderr** — 写 stdout 会被 glfw 的 `eval()` 解析 → SyntaxError

## 5. 画布节点 (L4)
- 实现: `src/lerobot/manifold/intact_node/` (node/model_adapter/data_source/robot_io/action_adapter/contracts/selftest), 注册在 `tools/gui/node_logic.py` 的 `_reg("intact", ...)`; 旁边有 SW 链节点 `sw_ds→sw_intact→sw_world→sw_video`
- 跨 venv: worker 子进程桥 (GUI py3.11 ↔ INTACT py3.10); 白名单透传字段时**别把 z_pred 丢掉**(曾导出了没人收到)
- 数据源: `set_data_source("official", task="cube")` → `$LOCAL_DATASET_DIR/datasets/<file>.h5`; 或 `l4_episode`
- 诚实机制: `trained=False` + reason 时**拒绝返回零动作**(stub 被 selftest 拒)
- 自检: `PYTHONPATH=src python -m lerobot.manifold.intact_node.selftest`
- 实测: chunk (8,10) · `candidate_sequences=0`(零搜索) · intent_norm≈0.48 · latency ~0.8s 首步

## 6. 与 L2/L3 对齐 (接哪、别接哪)
- L4 chunk (8~10 步) ↔ L3/引擎单步动作: 语义同族(连续动作), 但 **chunk 幅度 0.118 > 引擎单步限幅 0.02** ⇒ 需**重采样/缩放**(action_block=5 → chunk 展开到 ~40 控制帧)
- 坐标系: env 动作系 ⇄ 端口任务坐标系 用 `src/lerobot/manifold/flight.py` (`Flight.to_port/to_world`, 往返误差 0)
- L2 是**技能 Token 序列**(离散), 与 L4 连续动作不同维 ⇒ L2 定"做什么"、L4 定"怎么做", 靠编排器桥接, 不是替代
- 纤维丛层(`fiber_bundle.py`, SS_L4_FIBER=1): 只往 DiT 加 214 维条件 token; **direct 模式动作来自 intent_actor, DiT 不是动作来源 ⇒ 实测 A/B 无提升(48 rollout 全 75%)**, 默认关

## 7. 纪律
- 每次改动都要**同口径 A/B**(同 seed、每臂独立进程) + 零回退验证(`tools/verify_fiber_zero_regression.py`)
- L3 档逐位 hash 不可当判据(CPU bf16 FP 非确定, 已复现 3 次) → 判据用"新代码未进 + 结构不变 + L2 逐位相同"
- 单次评估不作结论: metaworld 布局跨进程漂移 ⇒ 多 seed 多重复
