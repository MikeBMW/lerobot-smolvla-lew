# Model Zoo 标准 lerobot 工程脚手架 (2026-08-12)

用户在 `~/lerobot-modelzoo/` 建的标准训练工程(对标 lerobot 官方结构, 脱离 GUI 独立跑)。
策略代码复用 `~/lerobot-smolvla-lew` fork 的 `src/lerobot/policies/`, 训练走容器 `zmax-std:1.0`。
可整体复制为新工程的模板。

## 目录结构

```
lerobot-modelzoo/
├── README.md               # 七模型清单 + 源码位置 + 用法
├── .gitignore              # configs/runs/ + outputs/train/* + data/* 不入库
├── configs/                # 7 个模型配置
│   ├── act.yaml            #   lerobot 标准 (policy.type=act)
│   ├── smolvla.yaml        #   (policy.type=smolvla)
│   ├── smolvla_lew.yaml    #   (policy.type=smolvla_lew, PreTrainedConfig.register_subclass)
│   ├── vla_touch.yaml      #   独立脚本参数记录 (train_vla_touch.py)
│   ├── awe_zflow.yaml      #   独立脚本参数记录 (train_awe_zflow.py)
│   ├── expert_mlp.yaml     #   蒸馏参数记录 (distill_expert.py)
│   └── expert_policy.yaml  #   官方专家基准说明 (无需训练, 纯注释 yaml → safe_load=None 合法)
├── data/                   # setup.sh 软链, 不复制 (磁盘铁律)
├── outputs/train/          # 训练产物
└── scripts/
    ├── train.sh            # 单模型训练 (容器分发)
    ├── train_all.sh        # 一键六模型
    ├── eval.sh             # 统一评估 (仓库 tools/compare_models.py)
    └── dataset_check.py    # 数据集校验 (零依赖)
```

## 容器挂载约定 (train.sh)

```
-v $PROJ:/modelzoo  -v $REPO:/app  -w /app  -e PYTHONPATH=/app/src
$SUDO $DOCKER_BIN run --rm --gpus all ... zmax-std:1.0 \
  -u -m lerobot.scripts.lerobot_train --config_path /modelzoo/configs/runs/<p>_run.yaml
```
- config 内 `output_dir` / `dataset.root` 必须写容器绝对路径 `/modelzoo/...`
- 独立脚本 (vla_touch/awe_zflow) 传 `--data-root /modelzoo/data/metaworld_act`
- 数据软链在 host 侧解析, docker -v 挂载后容器内可见 (软链目标在挂载卷内即可)

## 分发模式 (train.sh case)

- `act|smolvla|smolvla_lew` → `lerobot_train --config_path`
- `vla_touch` → `/app/tools/train_vla_touch.py --data-root ... --steps N --batch 8 --lr 1e-4`
- `awe_zflow` → `/app/tools/train_awe_zflow.py ... --max-frames 2000`
- `expert_mlp` → `/app/tools/distill_expert.py` (main(), 无 argparse, 内置 n_eps=300)
- 未知 policy → 报错退出; 镜像缺失 (`image inspect`) → 提示先构建

## steps 覆盖 (不污染标准 config)

```
mkdir -p configs/runs
sed -E "s/^(steps:).*/\1 $STEPS/" configs/$POLICY.yaml > configs/runs/${POLICY}_run.yaml
```
`configs/runs/` 进 .gitignore。验证 steps 生效: grep "^steps: N" runs/xxx_run.yaml。

## 假 docker 验证模式 (防误触发真实容器)

⚠️ **sudo 会重置 PATH** (secure_path) → 假 docker 放 /tmp + 只 export PATH 会被绕过,
`sudo docker` 执行的是真实 docker (本次真触发了一次 act 123 步训练, 立即 docker ps -q
--filter ancestor=zmax-std:1.0 | xargs docker kill 止血)。
正确做法: 脚本支持 `DOCKER_BIN="${DOCKER_BIN:-docker}"`, 所有 docker 调用用 `$SUDO $DOCKER_BIN`,
验证时 `DOCKER_BIN=/tmp/fakedocker ./scripts/train.sh act 77` (sudo 执行绝对路径 OK)。
fakedocker: `echo "FAKE-DOCKER: $*"; exit 0`。
验证断言: 输出含 FAKE-DOCKER 即分发正确。

## LeRobot v3.0 数据集格式 (dataset_check 兼容)

- v3.0: `meta/episodes/chunk-000` 分块文件 (不是每集一个 json!) + `meta/info.json`
- info.json 键: codebase_version / total_episodes / total_frames / fps / splits / features
- v2: `meta/episodes/*.json` 每集一个 (length 字段)
- 校验要点: info.json 存在、episodes 目录非空 (chunk-* 或 *.json)、帧数/集数打印

## 七模型源码位置 (用户问过)

| 模型 | 源码 |
|---|---|
| ACT | src/lerobot/policies/act/ |
| SmolVLA | src/lerobot/policies/smolvla/ (factory.py 139 行注册) |
| SmolVLA+LEW | src/lerobot/policies/smolvla_lew/ |
| VLA-Touch | tools/train_vla_touch.py |
| AWE-zFlow | tools/train_awe_zflow.py |
| MLP 蒸馏 | tools/distill_expert.py |
| 官方专家 | metaworld SawyerPegInsertionSideV3Policy |

## 陷阱

- `bash -n` 检查 sh 脚本用 bash (数组语法 `COMMON_VOLS=(...)` 在 dash 下 Syntax error)
- policy.type 校验: `smolvla` 注册于 factory.py, `smolvla_lew` 走 PreTrainedConfig
  register_subclass (配置 type 直接可用, 历史 config 文件复制粘贴常把 smolvla 写成 smolvla_lew)
- **git mv 代码进 src/lerobot/policies/<pkg>/ 后, 基于 `__file__` 的 ROOT 上溯层数必须重算**:
  YOLO 感知链 tools/ → src/lerobot/policies/yolo_3d/ 后 ROOT 从 dirname×2 改 dirname×4
  (yolo_3d→policies→lerobot→src→仓库根)。写 5 层会到 /home/xspace。验证用**真实 abspath 语义**:
  `os.path.dirname(os.path.abspath(文件))` 再上溯, 不要用相对路径字符串 dirname(会误判)。
  同步更新 import 引用: `from tools.yolo_state_aligner import` → `from lerobot.policies.yolo_3d.yolo_state_aligner import`
  (gen_metaworld_data.py 需先 `sys.path.insert(0, str(proj / "src"))`)。GUI 里 pkill 模式串 "train_yolo"
  仍匹配新路径, 不用改
- 新子包必须有 `__init__.py` 导出公共类 (YoloStateAligner), 否则 `from lerobot.policies.yolo_3d import YoloStateAligner` 失败
