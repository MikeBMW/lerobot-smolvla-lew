# 直驱接入 + 判闸 — 实测记录 (2026-09-12, Z-MAX / INTACT-JEPA 域内微调)

场景: 老倪要求"**不更改任何逻辑, 直接复制 INTACT 项目**": 模型输出 action 直接开机器人。
本文件记录真实命令、数字与踩坑, 供下次同类接入直接抄。

## 1. 数据侧: 域内数据集放到 8× (踩了 OOM 坑)

```
# 采集 (引擎真实渲染帧 + env 级动作 act=[dx,dy,dz,gripper] + obs[:39])
MUJOCO_GL=egl ./gui-venv311/bin/python tools/intact_domain_dataset.py \
    --seeds 0,1,...,299 --max-steps 600 --out-name zmax_insert_v2 \
    --part-frames 20000 --dest /home/ubuntu/stable-wm-cache/datasets
# → 每 2 万帧落一个 reports/zmax_insert_v2_partNN.npz (8 个), 打印每回合帧std (真图判据)

# 流式合并成官方 h5 (INTACT venv, 有 h5py) —— 峰值内存 = 一个 part
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_parts_to_h5.py \
    --parts 'reports/zmax_insert_v2_part*.npz' --out-name zmax_insert_v2 --validate
```

实测数字: 300 回合 / **151,671 帧** / done_rate 0.44 / 每回合帧std 55.5~56.0 (真图) / h5 7.5GB。
合并后官方加载器 OK: `len=147,171 · action_dim=4 · pixels std 55.9`。

踩坑 (都在真实会话里发生过):
1. **一次性 concat 15 万帧 ≈ 22GB → 进程被 OOM 杀, 一个文件都没落盘** (采集循环跑完 1095s 白跑)。
   修法 = `--part-frames` 内存闸 + 分块落盘。
2. **官方解析器要带扩展名**: `--validate` 里用裸名 `zmax_insert_v2` →
   `FileNotFoundError: Cannot resolve 'zmax_insert_v2': not a local path or HF repo id` (实际文件是 `zmax_insert_v2.h5`)。
3. **验证抛异常 → 后面的"删中间 part npz"没执行** → 7GB 中间产物一直占盘。
   修法: 验证包 `try/except` 只告警, 不阻断清理/训练。
4. h5 attrs 里补 `done_rate` (采集阶段按 part 记, 合并时按回合数加权) — 面板/台账要显示真实值。

## 2. 直驱 (模型动作 → env.step)

```
# 引擎钩子: 默认 None → 既有解析链/MLP 路径零改变
_dact = getattr(self, "_direct_act", None)      # 非 None = 该值就是 env 级动作
# 驱动脚本 (包 sched.decide 只取阶段标签, 指令 100% 来自模型)
MUJOCO_GL=egl INTACT_RUNTIME=root \
INTACT_POLICY=intact_goal_zmax_s3072/weights_epoch_8.pt \
./gui-venv311/bin/python tools/intact_direct_rollout.py --seeds 0,1,2,3 --max-steps 600 --device cuda
```
实测: 每回合 600 次真推理, 无报错; **直驱 0/4 vs 同轮解析链 1/4**。
下发动作 std = x 0.0072 / y 0.0025 / z 0.0082 (教师 0.153 / 0.0715 / 0.113) → 比教师小 20 倍,
物理上推不动, 阶段直方图一直停在"接近/对位"(近似常数指令)。

逆归一化 (唯一换算): 训练时 action 列被 z-score, `action_dim = frameskip(2) × 4 = 8`,
mean/std 用数据集同口径 (finite 行 + ddof=1) 落 `reports/zmax_action_stats.json`, 推理时 `a_raw = z·std + mean`。

## 3. 离线回放闸 (判决"动作头能不能用", 4 秒)

```
HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins INTACT_RUNTIME=root \
INTACT_POLICY=<ckptdir>/weights_epoch_N.pt \
/home/ubuntu/INTACT-JEPA/.venv/bin/python tools/intact_replay_check.py \
    --n 60 --stride 300 --device cpu --out reports/intact_replay_<tag>.json
```
输出 (数据集真帧 vs 教师动作, n=120):
```
dx  MAE=0.1235 pearson=+0.112 教师std=0.1723 预测std=0.0145
dy  MAE=0.0489 pearson=-0.183 教师std=0.0813 预测std=0.0028
dz  MAE=0.1034 pearson=-0.064 教师std=0.1134 预测std=0.0383
grip MAE=0.4784 pearson=-0.126 教师std=0.7144 预测std=0.0616
对照: 常数基线(教师均值) xyz MAE=0.0860 · 模型 xyz MAE=0.0919   ← 不如常数
```
⇒ 动作头塌缩到均值; slot0 / slot1 结果一致 (排除读错槽位) ⇒ 不上闭环, 先修训练。

## 4. 逐 ckpt 判闸守护 (无人值守)

```bash
while pgrep -f 'config-name <exp>' > /dev/null; do            # 训练在跑
  for f in "$CK"/weights_epoch_*.pt; do                        # 每落一个就评
    grep -q "GATED $(basename "$f" .pt)" "$LOG" && continue
    INTACT_POLICY="$f" python tools/intact_replay_check.py --n 60 --device cpu ... >> "$LOG" 2>&1
    echo "GATED $(basename "$f" .pt)" >> "$LOG"
  done
  sleep 30
done
```
要点: CPU 推理 (不与训练抢显存) · 幂等 (GATED 标记) · 训练结束后补评剩余 ckpt · 过闸即提前上闭环。

## 5. 微调配置与预算

```
# 域内微调 (hydra 覆盖; 关键 = 动作头权重 + epoch)
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True .venv/bin/python train.py \
  --config-name <cfg> output_model_name=<exp> data.dataset.name=<ds>.h5 \
  trainer.max_epochs=3 loss.intent.local_weight=1.0 loss.intent.goal_weight=1.0 \
  loader.batch_size=16 loader.num_workers=12
```
- 旧配置 `local 0.1 / goal 0.05 / forward 1.0` → 动作头只分到 ~15% 梯度 → 塌缩。
- ETA: 8,278 步/epoch ÷ 2.1 it/s ≈ 66 分钟/epoch (batch16 + workers12); batch24 在 8GB 卡 OOM。
- 30 epoch 按此速度 ≈ 50 小时 → 砍到 3 epoch (约 3.3 小时) + 逐 epoch 判闸。

## 6. 同口径对照 (为什么必须配对)

- 同 seed 配对 16 对可探测的最小效应 ≈ 2 对; 实测**默认参数重跑**基线成功率在 0.250~0.312 间抖。
- 一个候选首轮 4 胜 0 负 (0.25→0.50) 看似"有提升", 换新种子 1 胜 0 负 15 平 (≈无差异),
  再换 32 对 **0 胜 0 负 32 平** ⇒ 结论: 未复现, 不得进默认档。
- 噪声对照 (默认值当候选) 应 0 胜 0 负 = 测试台自洽, 零假阳性。
