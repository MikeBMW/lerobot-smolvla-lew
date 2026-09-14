# smolvla_lew: 续训配置坑 → 真执行接入 → DAgger 闭环 (2026-09-10 实测)

本文记录把训好的 SmolVLA-Lew 策略**真正接成引擎执行者**的完整路径, 以及每一步踩到的坑。
结果状态: ①续训到 30000 步完成 (gripper 未改善, 见文末) ②真执行接入跑通但闭环失败 (分布偏移)
③DAgger Round 1 采集/转换/训练流水线跑通, **效果尚未验证** — 不要把 ③ 当成已验证的成功方案。

## 1. 续训后必须补 config.json 的 `type` 键

训练写回的 `checkpoints/<step>/pretrained_model/config.json` **不含 `type`**,
而 `SmolVLALewPolicy.from_pretrained(dir)` 走 draccus choice 解码 → 报:

```
ParsingError: Expected a dict with a 'type' key for <Config>, got {...}
```

修 (每次续训 / 每次新 step 目录都要):

```python
import json
d = json.load(open(p))
if not d.get("type"):
    d["type"] = "smolvla_lew"
    json.dump(d, open(p, "w"), indent=1)
```

## 2. 续训步数语义 / checkpoint 软链

- `steps` 是**总目标步数**不是增量: 30000 步的 ckpt 想再训 1 万 → `steps=40000`。
  写成 20000/30000 会**立刻 End of training** (日志一闪就退, 像"瞬间训完")。
- `checkpoints/last` 是**软链** → 复制 checkpoint 用 `cp -rL` (裸 `cp -r` 复制软链本身,
  目标目录只剩断链, 随后 `No such file or directory`)。
- 换数据集续训 = 复制 ckpt 到新 output_dir + 改 `train_config.json` 的
  `dataset.repo_id/root` + `output_dir` + `steps`, 再 `--config_path=<新目录>/checkpoints/last/pretrained_model/train_config.json`。

## 3. 真执行接入 (引擎侧, 生产默认关)

`tools/gui/state_space_sim_real.py` 的开关惯例:

| 环境变量 | 作用 |
|---|---|
| `SS_L3=1` | 每 `SS_L3_EVERY`(默认4) 步: `env.render()` → 官方 pre → 策略前向 → 取 xyz 替换前馈 u_ff; gripper 仍由状态机 |
| `SS_DAGGER=1` (配合 SS_L3) | 逐帧缓存 `(frame, 39D state, 专家 u_ff, 模型动作, stage)` 到 `sim._dagger_buf` |

要点:
- 渲染帧与训练同源 (480×480) + `visual39` (引擎里现成的 cur18+prev+target)
- **专家标签零成本**: 引擎里先算 `u_ff = analytic_forward/forward` 再被模型替换,
  所以"替换前的那份 u_ff"就是天然对齐的专家动作 — 不需要额外跑专家轨迹
- 实测结论 (诚实): **单帧动作误差 0.05-0.16 仍闭环失败** (seed104 解析链 343 步成功 → 模型 1000 步失败)。
  这是 covariate shift, 不是接入 bug。

## 4. DAgger Round 1 流水线 (采集→转换→训练→评估)

```bash
# ① 采集: 模型驱动 rollout, 同时记录专家标签 (10 seed × 600 步 ≈ 1500 帧, ~1 分钟/seed)
MUJOCO_GL=egl SS_MUSCLE=0 SS_L3=1 SS_DAGGER=1 \
  gui-venv311/bin/python /tmp/dagger_collect.py --seeds "0,6,7,9,101,104,1,2,40,50" --max-steps 600
#   输出 /tmp/dagger_rN/seed<k>.npz (state/expert/model/stage/t) + seed<k>.mp4

# ② 转换: 追加为 episodes → 新数据集 (保住原数据集不动)
cp -r data/smolvla_peg_v8 data/smolvla_peg_v8_d1        # 先复制, 别原地追加
gui-venv311/bin/python /tmp/dagger_to_lerobot.py --src /tmp/dagger_r1 --dst data/smolvla_peg_v8_d1
#   action 列 = expert (专家动作) ← DAgger 的核心

# ③ 训练: 复制 ckpt 到新 output_dir + 改 config (dataset/root/output_dir/steps) 后 resume
# ④ 评估: 引擎闭环成功率对比解析链基线 (同 seed 集合, 多次重复取范围 — 见 SKILL.md 随机性陷阱)
```

### 数据追加的三个坑 (全踩过)
1. **新行 DataFrame 必须与旧 parquet 列完全一致**, 否则 `ValueError: All arrays must be of the same length`。
   本次漏了 `next.success`。**先 `pq.read_table(<data parquet>).column_names` 拿全列**, 再逐列 append
   (episodes parquet 同理: 用 `old_ep.to_pydict()` 的键遍历)。
2. 视频按 **episode 单独文件**是合法格式: 文件名 `file-{file_index:03d}.mp4`, 新 episode 的
   `videos/observation.image/file_index` 设为新 ep 号即可 (info.json 的 video_path 模板
   `.../file-{file_index:03d}.mp4` 自动适配) — 不一定非要合并单文件。
3. 帧时间轴: 每 4 步 1 帧的数据 → `timestamp = i/fps` (按视频帧走), 别写成物理步时间。

## 5. gripper (夹爪) 维 — 续训治不好 (30000 步实测)

| 步数 | 平均动作误差 | 抓取段 gripper |
|---|---|---|
| 10000 (v8) | 0.1505 | 真值 1.0 / 预测 0.0 |
| 30000 (续训后) | 0.1599 (**无改善**) | 仍 真值 1.0 / 预测 0.0 |

根因: gripper 是 0/1 二值, MSE 回归倾向输出条件均值 (≈0), 加样本不解决。判定 = xyz 维误差
0.01-0.08 而 gripper 维 0.3+。务实分层: xyz 由模型出 / gripper 走状态机。

## 6. 汇报口径 (老倪纠正过)

- 训练指标用**均值 + 逐 batch 波动区间** ("action_loss 均值 0.33→0.28, 波动 0.01~1.35"),
  不要拿单个低 batch 瞬时值当趋势
- 引擎规则跑出的成功率标注"引擎侧成绩, 非模型"
- 负结果直说 (续训没改善就说没改善), 不把未验证的迭代说成突破
