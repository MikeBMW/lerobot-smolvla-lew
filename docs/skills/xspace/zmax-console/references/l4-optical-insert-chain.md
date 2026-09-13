# 🌍 L4 · 光模块插拔链 (v5.5.37, 2026-09-13)

老倪: 「把红色小方块的抓取实验, 改造成光模块的抓取插拔实验」+「除了新生成的数据, 其它任何代码/接口都不动, 只是用新数据」

## 链条 (与 cube 链四节点同构, 只换任务)

```
🧪 光模块插拔 · 环境渲染图像源 (Z-MAX 引擎逐帧真图)       swds
🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)    swintact
🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step) swworld
🎬 插拔渲染视频 (从 Z-MAX 引擎取出 · 实况窗)              swvideo
(色带 🌍 L4 · 光模块插拔链 = 触发开关; 节点在名字含 L4 的 row_bg 内 → 只有 L4 档执行)
```

切任务 = 写 `data/intact_sw_task.json` `{"task": "optical_insert" | "cube"}`
(默认 optical_insert; `_sw_deploy(root)` 可再写 `data/intact_sw_policy.json` 指定 policy/stats/mode/max_steps/seeds/device)。
**不埋进代码分支** — 换任务不改 py 文件, 一眼可见 (老倪口径)。

## 两个 venv 的分工 (关键)

| 角色 | 解释器 | 为什么 |
|---|---|---|
| 引擎 RealStateSpaceSim (metaworld peg-insert-side-v3) | `gui-venv311/bin/python` | 只有它装了 metaworld |
| INTACT 模型 (torch/hydra/stable_worldmodel) | `/home/ubuntu/INTACT-JEPA/.venv/bin/python` | 由 `IntactRuntime` 起**子进程** (行式 JSON 协议), gui venv 里没有 torch 依赖链 |

桥 = `tools/intact_sw_optical_bridge.py` (跑在 gui-venv311)。
cube 链相反: 桥跑 INTACT venv (`tools/intact_sw_bridge.py`), 因为那个任务的 env (stable-world OGBCube) 本身在 INTACT venv 里。

## 桥的执行流 (真跑, 无加工)

1. **同 seed 解析链对照** (`mode=insert`): 真引擎跑通 → 末帧 (resize 224² CHW float32) = **目标帧**
   (`reports/intact_goal_frame_optical.npy`), 同轮再做一次 `mode=full` = 插→拔→AOI 全链视频 (可达性基线)
2. **模型直驱**: `sim._frame_sink` 内做一次真推理 → 写 `sim._direct_act` → **下一步**引擎用该值做 `env.step`
   (引擎 1179 行既有直驱入口; 非 None 时 act 直接取该值, 不经 u/K_ACT 与夹爪阈值化)。
   首步 `_direct_act = [0,0,0,GRIP_OPEN]` = 静止保持 (不是专家动作)。
3. 逐帧: spool `step_%06d.jpg` (224²) + `status.json` (原子 replace) + `status.jsonl` (一帧一行, 供互动查看器)
   + 480² mp4 (overlay 打标: 真推理次数 / 模型输出 / env 动作 / 插入深度 mm)
4. 末尾 ffmpeg concat 出合集 (⚠️ concat 列表里必须写**绝对路径**, 否则 ffmpeg 按 list 文件目录解析 → 找不到文件)

## 动作口径 (v4 数据集 = u 空间, 必须做量纲逆运算)

```
数据集动作列 = 引擎控制向量 sim._u_vec  (xyz 速度 m/s + 夹爪 [-1..1])
env.step 收的是 ±1 动作 → 按引擎**自己那套约定**还原 (state_space_sim_real.py:1183/1198 同源):
    u_raw = z * std + mean            # 训练归一化的数学逆运算 (z = 模型输出, 统计来自同一 h5)
    act[:3] = clip(u_raw[:3] / K_ACT, ±1)          # K_ACT = 0.5
    act[3]  = GRIP_CLOSE if u_raw[3] > 0.5 else GRIP_OPEN   # 0.6 / -1.0
```
若统计 json 的 `action_space == "env"` (v3 口径) → 直接 `clip(u_raw, ±1)` 下发 (与 `install_direct_act` 一致)。
统计一律用 `tools/action_stats_from_h5.py` **现算** (get_column_stats 同口径, ddof=1, 带 action_space 标注) —
权重与统计不同源 = 静默错动作, 不许手写常量。

## 实测踩过的坑

1. **stale status 竞态 (最坑)**: 上一轮 `status.json` 还是 `stage=done` 时, 节点等待循环第一轮就把它当成
   「本轮跑完」→ 光模块链读到了 cube 的终态 (env=OGBCube, 52 帧, cube 视频), 校验全红却查不出原因。
   **修法**: `_sw_start` 在 Popen **之前**先写 `{"stage": "starting"}` 作废旧状态 (`_write_status_file`)。
   判定法: 报错里出现"上一轮的任务名/帧数" = 读到旧 status。
2. **解释器选错**: 引擎桥用 INTACT venv 跑 → `ModuleNotFoundError: metaworld`; cube 桥用 gui venv → `No module named numpy`。
3. **CPU 推理**: 桥里 `--device cpu` (GPU 让给训练, 单卡 8G 抢显存必 OOM)。实测 0.37s/次推理
   (900 步 ≈ 5.5 分钟); 与训练并跑会把训练拖到 1.8 it/s (2.1→1.8), 别叠太多 CPU 任务。
4. **视频计数按前缀过滤**: 同一 `reports/intact_sw/video/` 里既有 `cube_sw_*` 又有 `optical_insert_*`,
   节点日志必须按任务前缀筛 (`optical_insert_` / `cube_sw_`) 否则把历史任务的视频算进本轮。
5. **旧任务产物混放**: cube 链的视频/帧会留在同一目录 → 换任务后先确认 spool/video 是否是本轮 (mtime/前缀)。

## 判闸口径 (离线回放, 与 v3 完全同口径可比)

```
./gui-venv311/bin/python tools/intact_replay_check_v3.py \
   --h5 <数据集.h5> --stats <同源 stats.json> --n 120 --stride 120 --device cpu --out <报告.json>
(INTACT_POLICY=<checkpoints 下 policy 名> INTACT_RUNTIME=root)
```
- v3 (env 口径, epoch1): 预测std/教师std ≈ **0.05** · 模型 xyz MAE 0.0203 > 常数基线 0.0189 → 输
- v4 (u 口径, epoch1): 预测std/教师std ≈ **0.07~0.16** · 模型 xyz MAE 0.0416 > 常数基线 0.0368 → 仍输 (改善但塌)

**塌均值的配置级根因** (直接从 config 读出来的, 不是猜):
① `loss.intent.local_weight=0.1 / goal_weight=0.05` 而 `forward_weight=1.0` → actor 在总损失里几乎不发声;
② `model.intent_actor.min_log_std = -5.0` → 高斯 std 可缩到 0.007, **"输出均值 + 极小方差"就是 NLL 的最优解**。
⇒ 塌缩是损失函数的最优解, 再多 epoch 只会更稳地塌。对策 = 新配置 (`intact_goal_optical_insert_v5.yaml`):
`local/goal_weight 1.0/1.0` + `min_log_std -2.0` (数据/代码/接口零改动)。

## 验收证据 (节点级, 走画布同一份代码)

`./gui-venv311/bin/python tools/verify_l4_optical_chain.py` — 11/11 PASS:
节点名→语义key 4/4 · 任务分派 · 部署档权重+统计存在 · 真跑整链 (ds 起桥并等终态) ·
1800 帧 · 1800 次真推理 · frame_std 56.5 (>5 真图) · 解析链 2/2=100% (插入 65.13/64.78mm · seed0 全链插→拔→AOI=True) ‖ 模型直驱 0/2 (过冲 643/553mm)。

**诚实标注** (写进 status.honest_note + 节点日志): 小样本随机起点演示档, 非官方 100 局口径;
模型直驱失败 = 权重真实水平 (与离线判闸一致), 不加工成"成功插拔"。

## 训练接力 (timeout 14400 会掐死 12 epoch)

`train.py` 被包在 `timeout 14400` (4h) 里, 而 12 epoch 需 ~9.2h (实测 46min/epoch) → 到点 SIGTERM
(v3 就是这样 rc=124, 只落 2 个 ckpt)。**接力守护** `l4_ab/train_intact_optical_chain.sh`:
等第一轮结束 → 取**最新** `weights_epoch_*.pt` → 下一轮 `init_weights_path=<ckpt> init_strict=true`
(用 hydra CLI 覆盖 `output_model_name/trainer.max_epochs`, 已验证可覆盖) 换名续训, 直到累计 epoch = TARGET,
每轮不覆盖历史 ckpt。环境变量: `CFG` / `FAMILY_V` / `TARGET` / `PER_RUN` / `DEADLINE`。
