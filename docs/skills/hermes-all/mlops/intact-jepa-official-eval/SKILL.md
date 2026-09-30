---
name: intact-jepa-official-eval
description: Use when 跑 INTACT-JEPA 论文权重官方评测或核口径/视频。
---

# INTACT-JEPA 论文权重 · 官方协议评测 (paper_runtime + Direct 零搜索)

## 触发
- VSCode ② 号 debugpy 配置 (`program=${workspaceFolder}/paper_runtime/eval.py`) 报错或要复跑
- 老倪要出 / 刷新「四任务总表」(pusht · cube · reacher · tworoom)
- 要判定某次评测数字能不能用 (局数/种子是否够官方口径)
- 要拿评测视频当证据给老倪看

## 路径地图 (本机实测)
```
repo      /home/ubuntu/INTACT-JEPA          venv  /home/ubuntu/INTACT-JEPA/.venv  (py3.10, torch 2.6.0+cu124)
运行时    repo/paper_runtime/               (eval.py / jepa.py / module.py / prior_only_solver.py / sitecustomize.py)
cache     $STABLEWM_HOME = /home/ubuntu/stable-wm-cache
  datasets/pusht_expert_train.h5 · tworoom.h5 · ogbench/cube_single_expert.h5(→../ 软链) ·
  reacher/reacher.h5 · dmc/reacher_random.h5 · zmax_datasets.json(清单, 控制台只读)
  checkpoints/<policy>/weights_epoch_5.pt   (例: recovery_delta_full_pusht_s3072)
结果      逐 seed: /home/ubuntu/l4_ab/intact_results/<task>_seed<N>.json + SUMMARY.md
一键脚本   /home/ubuntu/l4_ab/run_paper_direct.sh <task> [policy] [seed] [num_eval]
```
必带环境变量 (debugpy 配置里那套): `STABLEWM_HOME`、`LOCAL_DATASET_DIR`、`PYTHONPATH=$PR:$ROOT`、
`MUJOCO_GL=egl`、`PYOPENGL_PLATFORM=egl`、`CUBLAS_WORKSPACE_CONFIG=:4096:8`、`HF_ENDPOINT=https://hf-mirror.com`。

## 标准流程 (顺序别换)
1. **数据集门** — `ls -l $STABLEWM_HOME/datasets/<task>.h5`。
   报 `FileNotFoundError ... pusht_expert_train.h5` 时**先别怀疑代码**: 大归档常只下到 `.zst` 没解压 →
   走 `dataset-archive-provisioning` 技能 (含 verify-before-delete 回收)。
2. **预检** (mode 是位置参数; 不传 `--policy` 会假 FAIL):
```bash
cd $ROOT && STABLEWM_HOME=$CACHE ./.venv/bin/python scripts/preflight_check.py eval-official \
  --task pusht --cache-dir $CACHE --policy recovery_delta_full_pusht_s3072
```
   读法: `[FAIL] code integrity: modified:module.py,train.py` = **我们自己 INTACT 微调的改动, 不是坏**;
   `[WARN] git branch expected junhan found main` = 正常 (我们不在上游分支);
   `[PASS] dataset/<t>` + `[PASS] checkpoint: .../weights_epoch_5.pt (N tensors, sha256=...)` 这两条才是关键。
3. **正式跑** (带 `RUNTIME_SHA256SUMS` 指纹门, 5 文件必须一致):
```bash
bash ~/l4_ab/run_paper_direct.sh pusht recovery_delta_full_pusht_s3072 42 100
# 手工等价:
cd $ROOT/paper_runtime && python eval.py --config-name=pusht solver=prior_only \
  policy=recovery_delta_full_pusht_s3072 seed=42 eval.num_eval=100 output.filename=pusht_results_recheck_<date>.txt
```
   **官方口径 = 100 局 × eval seed 0/1/42**, 出均值±样本std 才算数。
   eval.py 结果文件是 **append 模式** → 复跑务必用 `output.filename=` 另开新名, 别把旧证据混在一起。

## 日志逐行读法 (被问"我都干啥了"时直接照这个讲)
| 日志 | 含义 |
|---|---|
| `Cached 'action'/'proprio'/'state' from '.../<task>.h5'` | 数据集**真的读到了**; 只用于算归一化统计 (dataset.stats), 不训练 |
| `Loading checkpoint from folder .../<policy>` | 加载论文权重 |
| `Created ViT-tiny from scratch {...hidden 192, 12 layers, 3 heads, 224, patch 14}` | 世界模型编码器按配置搭骨架, 随后灌权重 |
| `N valid starting points found` + 打印一串索引 | 数据集里合法(非终止)起始帧有 N 个, 评测从这里采样; 打印的就是本局起点索引 |
| `gymnasium ... Casting input x to numpy array` / `Backend tkagg is interactive backend` / `lance is not fork-safe` | 三条**无害告警**, 不影响结果 |
| `solver_timing.{get_cost_calls_mean, candidate_action_steps_mean}=0.0` + `actor_warmstart_enabled_mean=1.0` | 零搜索凭据成立 (Direct 直接出动作块, 意图 actor 真参与) |

## 结果口径铁律
- **不同局数不可比**。实锤: 同一 seed42 权重, 20 局 = 90.0% (18/20), 100 局 = 77.0% (77/100)。
  Wilson 95% CI 分别是 69.9~97.2% 与 67.8~84.2% → **区间重叠 = 纯抽样噪声**, 不能说"这次更好"。
- 调试档 (20 局 / 30 局) 的数字只能当**链路通了的证据**, 不得进总表, 登记时要显式标「调试档」。
- 已出基线 (与本机 09-12 记录一致, 可复现): pusht 79.33±4.93 (官方 79.67) · reacher 97.00±2.00 (官方 97.0) ·
  tworoom 78.67±4.04 (官方 78.67) · cube 待评 (官方 98.67)。
- 复跑"证明修好了"要说清: rc=0 **且** success_rate 与历史一致, 不是"文件存在了"。

## 评测视频 (老倪要的画面证据)
- 每局一个 mp4, 直接写在 **`$STABLEWM_HOME/env_<i>.mp4`** (不是 outputs/ 里)。
- 帧 = **3 面板并排 224×224 带标签**: `agent`(模型 rollout) | `dataset`(数据集真值) | `goal`(目标静图)。
  实测规格 736×288 · 50 帧 · 15 fps · 3.33s。
- **致命坑: 文件名跨运行复用** (`env_0..env_N` 每局同名) → 后一次跑会**覆盖前一次的 env_0..env_N**,
  同一次不同局数的两跑会互相污染。**跑完立刻归档** (拷到独立目录 + 按成败改名), 见
  `scripts/archive_eval_videos.py`。
- 成败对应关系: `episode_successes` 数组第 i 个元素就是 `env_<i>.mp4` 的成败 (False → 该局失败)。
- 自检 (我看不到画面, 只能用数值说话): `ffprobe` 看 帧数/时长/分辨率 + `ffmpeg` 抽一帧算 `std>5` (真图非黑帧)。
- 归档示例: `/home/ubuntu/l4_ab/intact_results/pusht_debug_0913_videos/` (18 个 `*_success.mp4` + 2 个 `*_FAIL.mp4` + README.txt)。

## 坑
- `python eval.py` 必须先 `source .venv` 或直接用 `./.venv/bin/python`; 系统 python3 没有依赖。
- 读 h5 **必须 `import hdf5plugin` 在最前**, 否则读像素时 `OSError: can't open directory (/usr/local/lib/plugin)`。
- `preflight_check.py` 的 mode 是位置参数 (`eval-official`), 漏了只会打 usage 不会跑检查。
- 评测走 CPU/EGL, GPU 只占几百 MB → 与同机训练并存时别默认"评测没在用 GPU", 用 job 里那条 GPU 取证看。
- 别用 `pkill -f eval.py` 收尾 (会连带杀自己所在的会话链); 等 rc 或用具体 pid。

## 参考
- `references/paper-runtime-eval-runbook.md` — 本条链路的实测转录: 命令、日志原文、指标数字、视频归档细节
- `scripts/archive_eval_videos.py` — 把 `$STABLEWM_HOME/env_*.mp4` 按成败归档成独立证据目录
- 相关: `dataset-archive-provisioning`(数据集缺失/解压/回收) · `robot-policy-eval-rollout`(策略 rollout 视频) ·
  `unattended-job-orchestration`(四任务接力 + 哨兵 cron)
