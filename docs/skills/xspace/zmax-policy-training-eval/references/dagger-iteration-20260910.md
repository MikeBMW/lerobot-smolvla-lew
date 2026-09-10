# DAgger 迭代管道 (2026-09-10) — 解 VLA 闭环分布偏移

## 何时用
模型真接入引擎闭环后**失败** (单帧动作误差小, 但闭环越走越偏 = covariate shift),
而解析链能成功 → 走 DAgger (用模型自己的 rollout 数据再训)。
**别指望单纯加步数**: L3 续训 10000→30000 步, 动作误差 0.1505→0.1599 无改善。

## 引擎侧开关 (tools/gui/state_space_sim_real.py, 已实现)
- `SS_L3=1` — 每 `SS_L3_EVERY`(默认4) 步: `env.render()` 480×480 → 官方预处理
  (`make_pre_post_processors(policy.config, pretrained_path=ckpt)`) →
  `SmolVLALewPolicy.select_action` → **模型输出 xyz**; `gripper` 仍由状态机管。
  生产默认关 = 解析链 (28 seed 46.4%)。
  注意: 输入 batch 必须带 `"task"` 字符串 (缺 → `TypeError: 'int' object is not iterable`
  在 `instructions = list(tasks)`); state 用引擎 `visual39` (39D = cur18+prev+target)。
- `SS_DAGGER=1` — 记录每步 `(帧, 39D state, 专家动作, 模型动作, stage)` 到 `sim._dagger_buf`。
  **专家标签 = 模型替换前的引擎 `u_ff`** (引擎先算解析动作再被模型覆盖) → 零额外成本、
  状态动作天然对齐 — 这是 DAgger 能成立的关键。

## 三件套脚本 (写在 /tmp, 建议入库 tools/ 防 /tmp 清理丢失)
1. `dagger_collect.py` — N seed 模型驱动 rollout → 每 seed `seedN.npz`
   (state/expert/model/stage/t) + `seedN.mp4` (av 写 h264, 25fps, 480×480 rgb24)。
   每 seed 重新加载策略 (~20s) 是主要开销; 10 seed × 600 步 ≈ 10 分钟。
2. `dagger_to_lerobot.py` — 复制原数据集 → **追加 episodes**, `action 列 = 专家动作`。
3. 训练 — resume from 上轮 ckpt, `dataset.root` 换 DAgger 版,
   `steps = 上轮 + 10000` (~2h/轮 on 4060)。

## 踩坑 (真报错)
- **`ValueError: All arrays must be of the same length`** — 补行时必须覆盖原 parquet
  **所有列** (本次漏 `next.success`)。data 列全集:
  `observation.state, action, episode_index, frame_index, timestamp, index,
  task_index, next.reward, next.done, next.success`; episodes parquet 列全集见
  lerobot-dataset-engineering。episodes 里 `dataset_from_index/to_index` =
  全局累积帧区间 (别用 <= 上界)。
- **🚨 `cp -r <in>/last <out>/checkpoints/` 会复制成实体目录** (last 是 symlink) →
  训练保存 ckpt 时 `symlink_to` 报
  `FileExistsError: '030500' -> outputs/train/<run>/checkpoints/last` → 训练崩。
  正确: **`cp -rL`** (跟随链接, 得到真实内容) 或复制编号目录后自建 symlink;
  崩溃后恢复: `rm -rf last && ln -s <最新编号> last` 再 resume (进度不丢)。
- 视频文件独立命名 `file-{ep_idx:03d}.mp4` 与 info.json 模板
  `videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4` 兼容。
- info.json 必须同步 `total_episodes` + `total_frames`。
- **续训会重写 `config.json` 丢掉 `type` 键** → `from_pretrained` 报
  `ParsingError: Expected a dict with a 'type' key` → 手工补 `"type": "smolvla_lew"`。

## 关键结论 (2026-09-10)
- **gripper 二值回归是天然死穴**: MSE → 模型输出均值≈0 → 真值 1.0 时预测 0
  (该抓不抓); xyz 学得好 (误差 0.01-0.08)。务实解 = **模型管 xyz + 状态机管 gripper**,
  或给 gripper 单独 BCE 分类头。
- L3 (v8 30000 步) 真接入闭环: seed104 解析链 343 步成功 vs 模型执行 1000 步失败
  = 分布偏移实证 (不是接入 bug)。
- 评估口径: 与解析链基线 (28 seed 46.4%, insert 裸跑上限 1000 步) 同 seed 对比,
  每轮超过才算有效。
- **诚实汇报口径 (老倪纠正过)**: loss 给均值 + 波动区间 (逐 batch 0.01~1.3, 别报单点峰值),
  引擎侧成绩标注"引擎侧, 非模型", 不夸大。
