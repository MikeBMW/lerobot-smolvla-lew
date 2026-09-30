# L4 流形预测器训练 + lerobot 本地离线训练打通 (2026-09-09)

## 背景
- L3 = smolvla_lew policy (SmolVLM2 冻结 + DiT-B ActionHead + LeWorldModel), L4 = 流形专家
  (predictor_layer.py: LatentPredictor(z,a)→z' + ManifoldReadout(z'→6D)) — SmolVLA policy 内
  **没有流形读出头**; "流形预测成功率" 的预测器 = 引擎旁路独立小模型, 训练数据 = 引擎轨迹。
- 6 维流形真值列 (sim_real 每帧发布, 与预测列同帧对照): progress/risk/V (接触流形) +
  eta/rem/dperp (性能流形); rem = 头到孔底剩余插深, dperp = 横向对心错位。

## 数据同构铁律 (本会话核心教训)
- 采集输入必须与引擎旁路 **同构**: 训练样本 z7 必须就是引擎 predict_manifold 的输入。
- **z7 可辨识性**: 原 z7 = [x−target, x−peg, grasped] (x=夹爪) — 插入段夹爪几乎不动而
  光模块头在进孔 → rem(头到孔底) 不可辨识 (rem 命中率 28% 上限)。修: 夹持后 x→光模块头
  `x + _grasp_off0 + geom['head_off']` → rem 命中率提升; 引擎 tr 落 `z7_vec` 字段,
  训练脚本直接消费 tr 字段 (不重算, 保证同构)。
- 轨迹字段: z7_vec / u_exec_vec[:4] (动作) / mani_progress·risk·V·eta·rem·dperp (真值)。
- 采集: R0 (vision=False, 秒级/轮) 多 seed × insert/full; **测试集用未训练布局族**
  (如 full seed 7/9), 训练/测试按 seed 分 — 测的是布局族泛化不是记忆。
- 结果 (v1, 342K 参数 3 层, 200ep/71s, 16872 帧): 未见 full 布局 帧成功率 0%→16.4%
  (6 维物理容差全中), 插拔作业段 38.2%, 浅插 3-6cm 段 77.9%; 分维 V 100/eta 93/
  risk 91/progress 90/dperp 48/rem 28; z' RMSE 0.043。

## 成功率判据坑
- **相对误差判据在真值≈0 的维度必死**: risk/V/eta 空闲帧真值≈0 → |e|≤0.5|true|+eps
  永假 → 成功率恒 0%。用**物理容差** (progress≤0.03, risk≤0.01, V≤0.01, eta≤0.05,
  rem≤15mm, dperp≤15mm), 帧成功 = 6 维全在容差; 再按 rem 分层 (深插<3cm/浅插/悬停/转移)
  报段成功率 — 转移段 rem 0.3m+ 而容差 15mm=5% 相对, 必然低, 分层才诚实可读。

## lerobot 本地离线训练打通 (无网环境跑 lerobot_train)
- **config 陷阱**: dataset.repo_id 是 draccus **必需字段** (删了报 Missing required field),
  但给了就触发 hub 检查 (list_repo_refs) → 离线必炸。两件套:
  ① runner 里 monkeypatch `huggingface_hub.HfApi.list_repo_refs = lambda *a,**k: _Refs()`
  (branches/tags 空列表的假对象);
  ② 仓库 src/lerobot/datasets/utils.py `get_safe_version`: hub 无 tag 时原来抛
  RevisionNotFoundError (且构造缺 response kwarg → TypeError), 加本地兜底
  `if version in ("main","local",""): return version`。
- 权重走 HF 缓存 + `HF_HUB_OFFLINE=1` (SmolVLM2-500M-Video-Instruct 5.7G 已缓存)。
- **数据集 meta 损坏坑**: data/metaworld_peg 声称 30 集/5400 帧, 实际 21 集/3780 帧,
  parquet 索引越界 ("Invalid key: 4345 out of bounds for size 3780") — 加载即崩。
  排查: info.json total_episodes vs meta/episodes 实际 vs 训练日志。episodes 抽稀列表也会
  索引错位 → 先删 episodes 行用全集试。原生成管道 tools/gen_peg_data.py 输出 npz,
  转 lerobot 格式的脚本未入库 (重建需考古)。
- 依赖: lerobot-venv (py3.12) 缺 transformers/num2words/diffusers → aliyun 镜像
  `uv pip install --python ~/lerobot-venv/bin/python <pkg> --index-url
  https://mirrors.aliyun.com/pypi/simple/` (uv 在 ~/.hermes/bin/uv)。
- 8GB 显存 (4060 Laptop): freeze_smolvlm + DiT-B + LEW 6 层 batch1 理论可跑但 2000 步
  小时级 — 长训练优先 4090/web 机 (有网, 管道正规)。

## 参考脚本 (会话内 /tmp, 未入库)
- 采集 collect_mani_data2.py (消费 tr['z7_vec'])、训练 train_l4_v3.py、
  评估 eval_v3_final.py; 权重 models/l4_mani_predictor_v1.pt (137KB, gitignore 不入库,
  分发走网盘)。
