# 本地离线训练: 续训 / 数据集 / 策略验证 (2026-09-10 实测)

⚠️ **本文修正 SKILL.md 里 "draccus resume 机制是坏的, 别折腾 resume" 的说法** — resume 可用,
只是必须三个条件全对。SKILL.md 请以本文为准。

## 1. 续训 (resume) — 三条件缺一即报 "A config_path is expected when resuming"

```bash
python -m lerobot.scripts.lerobot_train \
  --config_path=outputs/train/<job>/checkpoints/last/pretrained_model/train_config.json
```

① **必须等号形式** `--config_path=<path>`。`src/lerobot/configs/parser.py` 的 `parse_arg("config_path")`
按 **`--config_path=` 前缀**在 sys.argv 里找, 空格分隔 (`--config_path <path>`) 找不到 → 即便传了也抛
`ValueError: A config_path is expected when resuming a run. Please specify path to train.yaml`。

② **config_path 指向 checkpoint 里的 `train_config.json`** (不是 yaml, 不是仓库 configs/ 下的)。

③ 编辑该 json: `resume: true` + `steps: <目标总步数>` (例: 已完成 10000 → 写 30000)。
`output_dir` 保持**原训练目录** (从 `checkpoints/last` 续; 新建目录会丢 resume 锚点)。

启动前必查无并发训练 (`pgrep -f lerobot_train`) — 8GB 卡双训必崩。
日志观察: `Training: N/20000` 的 N 是**剩余步数** (续训 10000→30000 显示 /20000)。

## 2. 离线环境数据集加载 — repo_id 必须是本地路径

`dataset.repo_id: lerobot/pusht` (占位) 会触发 hub `list_repo_refs` 查询 → 无网直接炸
(`HF_HUB_OFFLINE=1` 也拦不住, 因为检查在 metadata 加载前)。

**正解**: `repo_id` 直接写**本地数据集路径** (`repo_id: data/smolvla_peg_v8`), 配合 `root:` 同路径。
`LeRobotDatasetMetadata(repo_id)` 判非 HF id 即走本地分支, 不发网络请求。

## 3. 手搓 LeRobot 数据集必补的三样 (缺一样训练崩)

| 缺什么 | 报错 | 修 |
|---|---|---|
| `meta/tasks.parquet` | metadata 加载抛错/`FileNotFoundError` | `pa.table({"task_index": int64[0], "task": ["任务名"]})` |
| `stats.json` 的 **min/max** | MIN_MAX 归一化取不到 → 崩 | 从 parquet 实算 min/max/mean/std 写入 (image 可用 ImageNet 常量) |
| 帧时间戳与视频对齐 | `FrameTimestampError: queried 11.08 vs loaded ...` | 见下 |

### 帧时间戳对齐 (每 N 步渲染 1 帧时)
采集时 **每 4 步渲染 1 帧** (RENDER_EVERY=4) → mp4 只有 1/4 的帧数。若 parquet 的 `timestamp`
写 `i/fps` (逐步), 时间轴比视频**快 4 倍** → 训练查帧越界。
**修**: `timestamp = (i // 4) / fps` (按视频帧对齐), 使 `ts_max ≈ 视频时长`。

## 4. 验证已训策略的真实能力 — 必须走官方预处理管道

**"直喂原始帧/state 得到的大误差" 是假象**, 漏了归一化。手写 batch 直喂会得到 ~0.35 的平均动作误差,
走官方管道只有 ~0.15 — 前者会让你误判模型没学会。

```python
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.factory import make_pre_post_processors
policy = <Policy>.from_pretrained(ckpt); policy.eval()
pre, post = make_pre_post_processors(policy.config, pretrained_path=ckpt)
item = ds[i]
item["task"] = "任务描述字符串"          # ← 关键: 见下
batch = pre({k: v.unsqueeze(0) for k, v in item.items()})
act = post(policy.select_action(batch))
```

**`batch["task"]` 必须是字符串**: `_prepare_model_inputs` 做 `instructions = list(tasks)`, 若数据集返回
`task_index` (int) → `TypeError: 'int' object is not iterable`。

### 判读分维误差定位短板
逐帧打印 预测 vs 真值 的每维误差, 能定位"模型到底哪里没学会"。实测 smolvla_lew_v8:
移动/插入段动作误差 0.008–0.055 (学得好), 但**抓取段 gripper 真值 1.0 而预测 ≈0** —
"裸 rollout 不抓" 的根因就是 gripper 时机没学会, 而不是整体动作不会。修法 = 续训 (加抓取段权重/更多步)。

## 5. CPU vs GPU 训练小模型

世界模型/流形预测器这类小 MLP (百万参数级) 在 CPU 上训 1000 epoch 可能 >17 分钟/epoch 级
(550 万参数 × 8 万帧), 而 4060 GPU 上 1000 epoch ≈ 12 分钟。**先 `nvidia-smi` 看卡空再上 GPU**;
`py-spy dump --pid <pid>` (sudo) 可确认进程是在真算 (栈停在 `torch/nn/modules/linear.py forward`)
还是在卡住 — 别凭"半天没输出"就判死。
