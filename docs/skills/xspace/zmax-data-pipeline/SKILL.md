---
name: zmax-data-pipeline
description: "Z-MAX 数据闭环: Orin采集→Mac→ECS中转→本地训练ACT。数据不通/中转/上传训练时用。"
---

# Z-MAX 数据闭环流水线

## 链路架构
Orin(192.168.23.10:8765 采集) → 小芳Mac(192.168.23.1:8769 中转) → ECS中转 → 本地4060训练(或web 4090)

## ECS 中转服务 (relay)
- 服务: `/root/zmax-relay/zmax_relay.py`（模板: `templates/zmax_relay.py`）
- 公网地址: `https://datadrive.world/api/relay/`（nginx 443 反代 → 127.0.0.1:39053）
- 端点: `POST /upload`（json 或二进制 npz，流式写盘）、`GET /latest`（拉取即删）、`GET /peek`（只读不删，二进制只回元信息）、`GET /status`、`GET /packages`、`POST /ci/validate`（Simulink 验证）、`POST /orin/heartbeat` + `GET /orin/status`（Orin 推理服务心跳 → 控制台状态条数据源，**独立于弹栈队列**，不占包队列）、**WS `wss://datadrive.world/ws`**（Orin WS 长连心跳 → ECS 广播 → 控制台订阅，实时毫秒级）
- 铁律: 缓冲总量 ≤100M，超限自动删最旧；`/latest` 拉取后即删，中转不留存（老倪明确要求）

## 部署步骤（ECS 39.102.211.79）
1. scp `zmax_relay.py` 到 `/root/zmax-relay/`
2. scp `scripts/start_relay.sh` 并执行 `bash /root/zmax-relay/start.sh`
3. nginx: `datadrive.world.conf` 加 `location /api/relay/ { client_max_body_size 200m; proxy_pass http://127.0.0.1:39053/; }`
4. `/etc/init.d/nginx reload`（宝塔环境 nginx 在 /www/server/nginx/sbin/nginx）
5. 验证: `curl https://datadrive.world/api/relay/status`

## 本地训练端（4060）
- 脚本: `tools/relay_train.py`（pull → to_lerobot → train 三模式）
- 环境: `uv sync --python 3.12`（PATH 需含 `/home/xspace/.hermes/bin`）; 或 `python3 -m venv .venv` + `.venv/bin/pip install torch torchvision datasets pandas pyarrow numpy draccus gymnasium`（venv 实际可能是 python3.12, 以 `.venv/bin/python --version` 为准; TMPDIR 指向磁盘装大包, 见 hf-dataset-subset）
- ACT 配置: `config_act_closedloop.yaml`；训练入口: `PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_act_closedloop.yaml`（**flag 是 `--config_path` 下划线**，不是 `--config-path` — 此 fork 的 draccus 包装, 后者报 `unrecognized arguments`）
- **所有训练/推理脚本必须用 `.venv/bin/python` 跑** (系统 python3.14 无 torch; act_infer.py 用系统 python 会 `ModuleNotFoundError: No module named 'torch'`)

## CICD 部署链路 (4060 训练产物 → ECS → Mac → Orin)
全链路已实测跑通 (2026-08-02): 84M model.safetensors 上传 37.9s HTTP 200, SHA256 一致。
```
4060 训练 → tools/cicd_deploy.py push (找最新 model.safetensors 推 ECS 二进制包)
         → ECS /latest (拉取即删)
         → 小芳Mac hermes_gateway_mac/cicd_pull_deploy.py (pull + scp 到 Orin)
         → Orin: tashan@192.168.23.10 / ts123 (sshpass)
```
- 4060 推送: `cd ~/lerobot-smolvla-lew && .venv/bin/python tools/cicd_deploy.py push`（自动找 `outputs/train/*/checkpoints/*/pretrained_model/model.safetensors` 最新文件）
- **弹栈队列 + 拉取中断 = 模型永久丢失 (2026-08-02 实测)**: `/latest` 拉取即删——小芳 84MB 模型下载 41MB 超时中断, 重试时队列已空, 模型没了, 必须重新上传。**推模型后若对端说"队列空/下载中断", 第一反应是重推同一 checkpoint**（`tools/upload_model.py <path>` 直接传路径, 不要怀疑链路挂了）。大模型拉取端也应避免超时中断（后台/流式 + 足够 timeout）。
- **模型传递别再依赖弹栈队列 → 用静态路径 (2026-08-02 最终方案)**: 弹栈队列 + 两端同时消费（小芳监听器 peek + 手动 curl /latest）会竞争抢包, 模型 404 丢失。终极解法: **scp 模型到 ECS 网站目录做静态文件**, 对端直接 GET 一次到位, 永不竞争:
  ```bash
  sshpass -p 'Nix19789' scp model.safetensors root@39.102.211.79:/www/wwwroot/datadrive.world/models/act_cartesian.safetensors
  sshpass -p 'Nix19789' ssh ... "chmod 644 /www/wwwroot/datadrive.world/models/*.safetensors"
  # 对端: curl -o model.bin https://datadrive.world/models/act_cartesian.safetensors
  ```
  **权限坑**: scp 默认 600 (root only) → nginx(www-data) 读不了 → HTTP 403。必须 `chmod 644`。safetensors 不在 nginx 静态后缀规则里也能直接下发（无 location 匹配时走默认 static）。
- Mac 拉取部署: `python3 cicd_pull_deploy.py`（pull→scp→Orin 加载, 部署到 /tmp/zmax_act_model.pt）
- 模拟数据生成: `tools/gen_demo_data.py`（300帧≈10秒@30fps → data/closed_loop/task_closed_loop.npz）
- **relay status/latest 端点必须匹配 `*` 不是 `*.json`**：二进制 npz 包用 `.npz` 后缀, status 用 `*.json` glob 会漏报 packages:0；/latest 二进制分支要回传原始字节 (Content-Type: application/octet-stream)

## WebSocket 状态中转 (2026-08-02 升级, 取代 HTTP 轮询为主通道)
老倪问"为什么不用 websocket"→ 升级: HTTP 5秒轮询 → WS 长连接（实时双向、断线即刻感知）。
```
Orin 推理服务 ──WS长连:8765──→ ECS ws_relay.py 广播 ──WS推送──→ 控制台 GUI (QWebSocket)
  (5秒心跳, 断线自动重连)        (wss://datadrive.world/ws, nginx 反代已就绪)   (连接即收初始状态)
```
- ECS WS 服务: `/root/zmax-relay/ws_relay.py`（websockets 16.1.1 已装; 启动用 `bash /root/zmax-relay/start_ws.sh`; 模板见 `templates/ws_relay.py`）
- 协议: Orin→ECS `{"type":"heartbeat", online, model, infer_count, last_infer_ms, uptime}`; ECS→控制台 `{"type":"orin_status", ...last_seen}`; 新客户端接入立即推当前状态（打开即有数据）
- **nginx `/ws` location 是遗留配置**（已指向 127.0.0.1:8765, 8765 原本空闲）→ 直接复用, WS 服务绑定 8765 即可, 无需改 nginx
- Orin 端 `orin_infer_service.py`: WS 主心跳 + **HTTP 兜底双通道**（`http_fallback()` 10秒 POST /orin/heartbeat）; Orin 无 websockets 库时自动降级纯 HTTP（`try import websockets except ImportError`）
- 本地测试 WS: `.venv/bin/python` 需先 `uv pip install --python .venv/bin/python websockets`（venv 里没装）
- 验证: 模拟 Orin 推 3 次心跳, 控制台端逐条收到广播 = 链路通

## lerobot fork 训练配置 Schema (2026-08-02 六轮踩坑实测, 勿再逐条试错)
此 fork (`lerobot-smolvla-lew`, src/lerobot/configs/parser.py 包装 draccus) 与上游格式不同。正确结构:
```yaml
output_dir: outputs/train/act_closed_loop
job_name: act_closed_loop
policy:
  type: act
  push_to_hub: false        # 必需: 否则 validate 报 "'repo_id' argument missing"
  repo_id: MikeBMW/zmax-act-closedloop   # repo_id 放 policy 下, 不放顶层
  n_obs_steps: 1            # ACT 只支持 1! 设 2 报 "Multiple observation steps not handled yet. Got `nobs_steps=2`"
  n_action_steps: 7
  chunk_size: 7
  dim_model: 256
  dim_feedforward: 1024
  n_heads: 8
  n_encoder_layers: 4
  n_decoder_layers: 4
  use_vae: true
  latent_dim: 32
dataset:
  repo_id: lerobot/pusht    # 占位即可, 真正数据在 root
  root: data/closed_loop    # 本地 npz 目录 (observations/states/actions/task_name/fps)
  episodes: [0]
  use_imagenet_stats: true
batch_size: 8
steps: 1000                 # 此 fork 无 num_epochs! 用 steps
num_workers: 0
persistent_workers: false
log_freq: 100
eval_freq: 500
save_freq: 500
save_checkpoint: true
seed: 1337
optimizer:
  type: adam                # lr 必须在 optimizer 块下, 顶层 lr/learning_rate 报错
  lr: 1e-4
  weight_decay: 0.0
wandb:
  enable: false
```
**实测报错过的字段 (全部踩过)**: `--config-path` 连字符 → unrecognized; 顶层 `training:` 块 / `learning_rate` / `offline` / `device` / `repo_id` → `The fields ... are not valid for TrainPipelineConfig`; `policy.num_inference_timesteps` → ACTConfig 无此字段 (那是 smolvla 的); `policy.n_obs_steps: 2` → Multiple observation steps not handled yet。4060 实测: 1000 步 loss→1.962, 13-18 step/s, 1分16秒, GPU 0.39GB; 产物 `outputs/train/<job>/checkpoints/<step>/pretrained_model/model.safetensors` (~84M)。

## metaworld → ACT 训练/部署 (2026-08-01 全链路实测跑通)

### 1. parquet → npz 转换 (`tools/ci/prepare_metaworld.py`)
```bash
.venv/bin/python tools/ci/prepare_metaworld.py   # 输出 data/metaworld_act/{train,val}.npz
```
- **图像列是 `{'bytes': PNG bytes}` dict** (不是裸 bytes/数组!) — 必须 `img["bytes"]` 取出后用 PIL 解码: `Image.open(io.BytesIO(img)).convert("RGB").resize((128,128))`。只判断 `isinstance(img, bytes)` 会全部失败 → `np.stack` 报 "need at least one array to stack"。
- 按 episode 划分 train/val (同 episode 帧不能跨 split), 不要按帧随机切。
- 产出: observations (N,3,128,128) float32 [0,1] + states (N,4) + actions (N,4)。

### 2. 训练 (`config_act_metaworld.yaml`, 300 步 smoke)
```bash
cd ~/lerobot-smolvla-lew && export TMPDIR=$HOME/pip-tmp WANDB_MODE=disabled
.venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_act_metaworld.yaml
```
- 关键配置: `dataset.root: data/metaworld_act` (本地 npz 目录, repo_id 只是占位) + `use_imagenet_stats: false` + `save_freq/eval_freq: 150`。
- 4060 实测: 300 步 36s, loss 3.66→3.33, 13 step/s, GPU 0.39GB — smoke 训练非常快。
- checkpoint: `outputs/train/act_metaworld/checkpoints/{000150,000300}/pretrained_model/` (含 model.safetensors + preprocessor/postprocessor)。

### 3. 推理验证 (部署前置)
```bash
cd tools/gui && /home/xspace/lerobot-smolvla-lew/.venv/bin/python act_infer.py \
  ../outputs/train/act_metaworld/checkpoints/000300/pretrained_model --device cuda
```
- 成功标志: "✅ ACT 推理验证通过" + 输出动作 shape (1,2)。21.9M 参数, 首帧 243ms 后续 0ms。

### 4. 模型验证器 (CI 第一环)
```bash
python3 tools/ci/validate_flow.py flow.json --strict   # Simulink 工作流标准合规 (对标 Model Advisor)
```
详见 zmax-console §11 CI/CD 管道。

### 5. Simulink 验证 CI (2026-08-02 新增, 对标 MathWorks "Continuous Integration for Verification of Simulink Models")
- 验证器: `tools/gui/simulink_ci.py`（8 项检查: 格式/版本/节点Schema/连线/DAG无环/端口匹配/参数类型/仿真执行; 输出 JSON + HTML 报告）
- 本地: `python3 tools/gui/simulink_ci.py validate flow.json --report ci.html` / `pipeline` / `test`（内置回归）
- GitHub Actions: `.github/workflows/simulink-ci.yml`（push 触发, paths 限定 simulink-spec.md + simulink_*.py）
- ECS 端点: `POST https://datadrive.world/api/relay/ci/validate`（web 配合点; 内嵌 import run_checks, 别用 subprocess 传 bytes）
- 部署到 ECS: scp `simulink_ci.py` → `/root/zmax-relay/`（端点 sys.path 引用它）
- web comfyui_mock_ecs.py 的 `detect_model` 需兼容 dict 节点 (simulink 规范传 dict 列表, mock 原只接受 str 列表) → 加 `isinstance(nodes[0], dict)` 分支提取 name

## 本地 LeRobot v3.0 数据集构建 + metaworld 数据生成 (2026-08-02 六小时实测)
从 raw 采集 JSON / metaworld npz 构建 `LeRobotDataset` 能加载的本地数据集，坑极多（hub 覆盖、parquet float32、frame_index/timestamp 全局化、视频帧数一致、ACT delta 超界、WSL 渲染后端）。**完整清单见 `references/lerobot-dataset-format.md`**，要点：
- **⚠️ meta 模板掩盖真实维度 (2026-08-02 重大坑)**: `data/metaworld_act`、`data/closed_loop` 的 meta/info.json 是 pusht 模板拷贝 (state 2D/96x96/25650帧) → LeRobotDataset 按 meta features 读数据, 训练实际用 pusht, 本地 npz 从未被使用。**训练后必须查模型 `input_features` 验证真实维度** (state [2]+img[96,96,3] = pusht 数据)。治本: 用 `tools/npz_to_lerobot.py` 按 npz 真实维度重建数据集 (见 `references/npz-to-lerobot-metaworld.md`)
- 视频必须 **PyAV h264** (cv2 mp4v 无关键帧索引 → 解码失败); **所有 episode 共用一个视频文件 (file_index=0), timestamp 全局累计** (每 episode 独立视频+全局 ts 会超界)
- metaworld 3.x: `set_task` 必需 + Gymnasium API (reset 返回元组); joint 采集 state 取 `qpos[0:6]` (6D 对齐 Orin), 勿拼夹爪 (7D 致 Stage3 迁移维度不匹配); 采集 subprocess 需 `DISPLAY=:0 MUJOCO_GL=egl`
- **expert 策略采集 (2026-08-02)**: `tools/collect_metaworld_joint.py --policy expert` 用 metaworld 自带脚本策略 (`metaworld.policies.sawyer_{task}_policy`, get_action(obs)) 采高质量演示 (2000帧/20ep), 替代随机动作 (500帧) — Sim2Real MSE 0.0355→0.0051 提升 7 倍; random 策略保留 `--policy random`
- **S2 评估必须留测试集 (2026-08-02)**: eval_ds(root, test_ratio=0.2) 只评估**尾部 20% 帧** (训练用前 80%), 否则同分布全量评估是过拟合假象 (MSE=0.0000/100%); 训练集评估无参考意义
- **action 恒等修复**: 采集端把 state 当 action 记录 (`action==state`, 各轴均值全同) → 训练学恒等映射。检测 `np.allclose`, 修复为关节速度差分 (`tools/fix_orin_action.py`, 末帧前向差)
- 必须先修 fork 的 hub 覆盖 bug（本地 info.json 存在时跳过 snapshot_download，否则 root 被 pusht 覆盖）
- parquet 用 pyarrow `pa.list_(pa.float32(), N)` 写，pandas 的 double list 会 CastError
- `frame_index` 用**全局视频序号**（0..N-1，与 index 一致）；`timestamp` 用 **episode 内相对**（i/30.0，reader 自动加 from_timestamp，勿全局化——见下方双重偏移根因）
- 视频必须 `file-000.mp4` + `.metadata`；ffmpeg 合并用 `-vsync 0 -fps_mode passthrough`（`-vsync cfr` 会丢帧致超界）
- ACT `n_action_steps=7` 查未来帧会超全局视频末尾 → 每包独立视频文件（方案2）
- metaworld 渲染：`DISPLAY=:0 MUJOCO_GL=glfw`（WSLg）；reach-v3 action 是 4D(dx,dy,dz+gripper) 不是 6D
- 生成器: `tools/gen_metaworld_data.py`（--eps N --steps M）、6D真机: `tools/build_orin6d_dataset.py`、高清融合: `tools/build_hd_dataset.py`

### timestamp 双重偏移超界 (2026-08-02 终极根因, 勿再用"全局化"方案)
**timestamp 必须用 episode 内相对值 (0, 0.033, ...)，不是全局！** 证据链:
- `dataset_reader._query_videos` 会把 `ep[f"videos/{vid_key}/from_timestamp"]` **加到查询 ts 上** (shifted_query_ts)
- 若 parquet 的 timestamp 已是全局绝对（total/30.0），再加 from_timestamp = **双重偏移** → torchcodec 帧号翻倍（实测 1286 = 643×2）→ `Invalid frame index=1286 must be less than 515`
- 修复: parquet timestamp 用 `i/30.0`（episode 内相对），reader 自动加 from_timestamp 后 = 全局正确位置
- 症状: 单帧读取 OK、训练到中途才报超界（delta 查询触发）；`ds[i]` 直接读最后帧正常但 `ds[750]` 报 1393

### episode_index 必须连续编号 (2026-08-02 IDLE 过滤后实测)
IDLE 帧过滤后**包索引不连续**（如缺 ep15），若 episodes 文件保留原始 si:
- LeRobot 用**位置索引**查 episodes → `Invalid key: 24 out of bounds for size 24`（数据 parquet 有 24 个非空 episode 但 episodes 文件 24 条含空包错位）
- 修复: build 时用独立计数器 `ep_idx` 连续编号（0..N-1），数据 parquet 与 episodes 文件**都**用 ep_idx，空包不 append
- IDLE 帧 (action==state 值完全相同) 无训练价值且污染模型 → build 时 `if "IDLE" in label.upper(): continue`

### 闭环守护并发锁 (2026-08-02)
训练进行中新数据到达会重建数据集 → **正在训练的数据被删** → `Invalid key: 22 out of bounds`。
修复: auto_loop.py 用 LOCK 文件（`outputs/train/.loop_lock`）——LOCK 存在时跳过新包留待下一轮（且**不**加 SEEN，否则永久跳过）；try/finally 释放。

### glob 返回 str → str/str 崩溃, 守护自动上传静默失效 (2026-08-02 晚)
`train()` 里 `ckpts = sorted(glob.glob(...))` 返回 **str 列表**, 直接 `ckpts[-1] / "pretrained_model" / "model.safetensors"` = `str / str` → 抛 `unsupported operand type(s) for /: 'str' and 'str'`, 被外层 except 吞掉只打一行 `⚠️ 错误`。**症状: 训练日志 End of training 正常, 但守护日志同一秒报 str/str —— 模型从未自动推回 ECS**（当时所有 v1-v3 模型都是手动 scp 的, 直到修这个 bug 全自动闭环才真正闭合）。
修复: `ckpts = [Path(c) for c in ckpts if "last" not in c]`（Path 才能 `/` 拼接）。
诊断要点: 训练成功但守护报"错误: str/str" → 先看 train() 返回路径的拼接类型, 别查 build/upload。

### 全自动闭环首次闭合判定 (2026-08-02 晚)
守护自动推模型成功标志: 守护日志 `✅ 训练完成: ...model.safetensors` → `🚀 模型已推回 ECS` + ECS relay.log `📥 收到二进制 pkg_*.npz`。三者齐 = 采集→训练→推送全自动无人值守成立。

## 五模型对比评估 + rollout 视频 (2026-08-05 实测)
### train_curve JSON 契约 (find_ckpt 读它, 缺字段=模型被跳过)
`tools/compare_models.py` 的 `find_ckpt(policy)` 读 `reports/train_curve_<policy>.json`, 字段:
```json
{"ckpt": "outputs/train/act_*/checkpoints", "step_s": 15.0, "curve": [[0,1.6],[10,1.42],...]}
```
- **curve 必须是 `[[step, loss], ...]` 二元组列表** — 写成纯 float 列表会让 generate_report.py `curve_stats` 崩 `TypeError: 'float' object is not subscriptable`
- **缺 train_curve_<policy>.json = 该模型被跳过** ("无 checkpoint, 跳过") — 训练成功但文件没写/被中断时, checkpoint 存在也读不到。可手动补: 读最新 `outputs/train/<policy>_*/checkpoints` 目录 + 写 JSON
- **AWE-zFlow 曲线缺失根因 (2026-08-05)**: `train_awe_zflow.py` 的 `_log_loss` 只 `print` (给 GUI Scope 解析), **从未 append 到列表** → 最终 JSON dump 无 `curve` 字段 → generate_report 崩 + Scope 无曲线。修复: `_log_loss` 里 `curve.append([step, round(loss,6)])` (闭包捕获同函数作用域列表) + JSON dump 加 `"curve": curve`
- 五模型: act / smolvla / smolvla_lew / vla_touch / awe_zflow; vla_touch+awe_zflow 的 checkpoint 是 `model.pt`(torch.save 含 state_dict+config+stats), 不是 from_pretrained 目录 — compare_models/rollout 加载要走 `importlib.util.spec_from_file_location` 读训练脚本类 + `torch.load(model.pt)`

### metaworld rollout 黑屏修复 (2026-08-05 实测)
rollout 视频全黑 (var=0.0, 60帧全零) 的根因:
- **`env_cls()` 默认 render_mode=None → `env.render()` 抛 AttributeError ("Unexpected mode: None")** → 脚本 except 捕获后填全零帧 → 视频黑屏
- **修复: `env_cls(render_mode="rgb_array")`** — 实测渲染 var=4376 真图像
- 环境变量要在 import mujoco/metaworld 前设置: `os.environ.setdefault("DISPLAY", ":0")` + `MUJOCO_GL=glfw` (WSLg)
- V3 env 的 obs 是 numpy 数组 (非 dict), 不含图像 — 只能靠 `env.render()` 拿帧
- 验证: `.venv/bin/python -c` 读单帧 `Image.open(...).convert('RGB')` + `np.asarray().var()` > 1000 = 真图
- 拼多模型对比视频: 各模型 rollout 帧 → PIL 并排 canvas → `ffmpeg -framerate 15 -i cmp_%04d.png -c:v libx264` (用 .venv 的 python/numpy, 系统 python3.14 无 numpy)

### rollout_video.py 扩展 5 模型
- argparse choices 要加 `vla_touch, awe_zflow` (只加 load_policy 分支不改 choices 会报 invalid choice)
- ckpt 查找 cands 要含 `000050` (50步快速验证 checkpoint)
- 用 `os.path.join(ROOT, "tools", "train_*.py")` (ROOT 是 str, `ROOT / "tools"` 会 TypeError)
- 顶部 import torch + from pathlib import Path

## 容量上限 (2026-08-03, 防磁盘满)
- 单包/缓冲上限 100M: nginx `client_max_body_size 100m` + relay `MAX_PKG` (上传>100M 返回 413)
- `tools/disk_guard.py`: orin_live 限60包 / 训练产物保留4个 / loop_train.log 限5MB截断 / dds_flow 限2万行 / tmp 清7天前; 每小时自动跑
- ECS logrotate: `/etc/logrotate.d/datadrive` (datadrive.world.log/error.log daily 100M 3份) + `/etc/logrotate.d/zmax-relay` (relay.log/ws_relay.log daily 50M 2份) — relay.log 曾涨到 274M 撑爆 40G 盘
- ECS 40G 盘 80% 时清: `truncate -s 0 /www/wwwlogs/*.log /root/zmax-relay/*.log` + `rm archive/snap_*.jpg` + 重复模型(relay/models 与网站 models 双份)

### 光模块数据训练 + MLP 蒸馏插入成功 (2026-08-07 实测, "要能插入"达成)
- **光模块数据生成**: `tools/gen_peg_data.py --eps 30 --out data/metaworld_peg_v2` — 用官方专家 `SawyerPegInsertionSideV3Policy` 采样成功轨迹 (30 eps/5850帧/图像128/corner2视角与视频一致), 只留 inserted 轨迹; 失败轨迹 150 步提前终止省渲染时间。→ `npz_to_lerobot.py` 转训练格式 (`data/metaworld_peg_lerobot`)。
- **插入检测**: `tools/rollout_peg_check.py --policy <p> --n 5` — metaworld 环境 rollout N 次, 判定: peg 抬升 >0.05 (相对初始 z) + 孔距 <0.05 = 插入成功。输出 "✅ 插入成功/🟡已抬起未插入/❌没抬起" + 成功率。
- **ACT 光模块 4000 步 loss 0.585 但插入 0/5** (没抬起) — loss 收敛≠行为成功, 24 eps 数据对长程插拔不够/ACT 架构局限。**别只看 loss 就交付, 必须跑插入检测**。
- **MLP 蒸馏 = 最快插入成功路径**: `tools/distill_expert.py` (collect_expert_data 专家采样 300 eps + 15 epochs MLP 39D→4D) → **2/5 插入成功 (最小孔距 0.011m), 5/5 抬起**。简单模型从专家动作直接学, 比大模型长训更快见效。老倪"至少一次插拔成功"硬指标靠它达成。
- **ExpertMLP 加载三连坑** (rollout_video.py load_policy):
  1. ckpt 是 `.pt` 文件非目录 → 须特判 `if policy == "expert_mlp" and os.path.isfile(base_dir)` + `importlib.util.spec_from_file_location` 读 distill_expert.py 的 ExpertMLP 类 + `torch.load(base_dir)["model"]` (键是 `"model"` 不是 `"state_dict"`)
  2. **必须设 `pol.state_dim = pol.obs_dim`** — st_dim 推断 `getattr(policy, "state_dim", 2)` 默认 2 → forward `mat1 (1x2) vs (39x512)` RuntimeError → 动作全零。症状: 视频动作均值 0.0
  3. **ExpertMLP 无 select_action** → rollout_video 推理分支和 rollout_peg_check 都要加 forward 分支: `elif hasattr(policy, "obs_dim") and not hasattr(policy, "model"): pred = policy(batch["observation.state"])` — 漏了走 else(awe 4参) 报错→except→零动作
  4. rollout_video `--policy` argparse choices 要含 `expert_mlp, expert_policy` (只加 load_policy 分支不改 choices 报 invalid choice)
- **视频重生成统一**: `rollout_video.py --policy <p> --steps 60 --task peg-insert-side-v3 --camera corner2 --rotate-ccw` (corner2 能看到插槽的视角, 与 MLP/专家原版一致; 默认 corner 视角看不到插槽 — 老倪"前五个看不到插槽")
- **训练磁盘铁律**: smolvla 系 ckpt 1.4G/个, 4000 步默认保存 ≈25 个 = 35G → config 加 `save_freq: 500` 控制 + 训练完每目录只留最后 ckpt (`ls checkpoints | grep -E '^[0-9]+$'` 保留最大删其余)

## 队列维护 / stage_act 打标 / 现场直播 (2026-08-02 联调实测)
### 队列清理: 快照包 vs 数据包
- relay 队列会堆积 `orin_snapshot` 快照包（`meta.source == "orin_snapshot"`, 内容 `snapshot_b64`, frames=0）——小芳快照功能没停时会堆到几千包（实测 3058 包/38M）。
- 清理只留数据包: 遍历 `data/*.json`, `meta.source == "orin_snapshot"` 删除, 保留 `source == "orin"` 的 stage_act 数据包。清完 3055 删 → 3 留, 38M→384K。
- 根因是快照推流占用队列 → 小芳停快照 + web 开 `POST /api/snapshot/img` 静态写入端点后恢复。

### stage_act 打标数据
- 真实采集包 meta 带 `stage_act: true` + `labels: {动作名: 帧数}`（如 `{"IDLE": 142}`、`{"取料": 30}`）。
- 机器人空闲时标签全 IDLE 属正常（motion 是事件触发型, 空闲静默）——**只有非 IDLE 标签才值得训练**。
- 联调监控: `tools/live_monitor.py`（后台跑, 每 30s 轮询 `/status`, SEEN 集合去重; 新包且 `labels` 含非 IDLE → pull 保存 `data/orin_live/live_*.json` → 后台触发训练; IDLE 包跳过）。启动: `terminal(background=true) .venv/bin/python tools/live_monitor.py`。
- **监控必须过滤快照包 (2026-08-02 实测)**: 队列里 `orin_snapshot` 包每 30s 一个、无 frames, 不过滤会刷屏且 SEEN 集合被快照包占满。`src == "orin_snapshot"` 时 `continue` 跳过（在 has_action 判断之前）, 只处理 `src == "orin"` 数据包。

### 快照归档 (现场画面落盘, 2026-08-02)
- `orin_snapshot` 包结构: `snapshot_b64`(JPEG ~9KB) + `current_state`(如 AOI_4) + `all_states`(20 状态) + `timestamp`。**frames=0, 不能训练, 但图像是真实现场画面**。
- 老倪问"数据跑哪了"时能答: 快照堵在 relay 队列 → 归档到 `/root/zmax-relay/archive/`（`snap_<ts>_<action>.jpg` 解码落盘 + 同名 .json 存 current_state/all_states/action）+ 从队列删除。实测 411 帧一次归档。
- **上传即归档 (2026-08-02 最终版)**: `/upload` 端点收到 `meta.source == "orin_snapshot"` 或带 `snapshot_b64` 的包 → **直接解码归档到 archive/ 并从请求路径返回, 不进训练队列**。从此快照不再堆积队列, 无需定期清理; 队列只保留可训练的 orin 数据包。清理历史残留时按 `meta.source` 判别删除。
- **帧端点优先级: 归档快照 PRIMARY (2026-08-02 实测)**: `/cam/latest.jpg` 和 `/cam/status` **先读 archive 最新 snap_*.jpg**（快照每 ~1s 更新 = 真实现场）, CAM_DIR 实时推帧目录其次（可能残留已停止的模拟推帧旧图, age_s 会涨到几分钟）。顺序反了页面就"图像不动"。验证: 隔 2s 拉两次 diff 字节 + status age_s < 2。
- **/peek 归档兜底 (2026-08-02 实测)**: 页面状态机轮询 `/peek` 渲染 current_state + snapshot_b64——快照自动归档后队列只剩数据包 → peek 拿不到快照 → 状态/图像全停。修复: 队列空时 `/peek` 回退返回最新归档快照 `{archived_snapshot: true, current_state, all_states, action, timestamp, snapshot_b64(重新base64)}`。队列优先、归档兜底; 队列里有残留二进制包会遮蔽兜底, 排空队列才能看到兜底路径。
- 真实帧 vs 模拟帧判别（np 分析）: 唯一颜色数 **>500 = 真实场景**（快照实测 4371 色, 亮度 std 32.6）, **==1 或 <50 = 纯色测试/占位帧**（std≈0）。老倪说"不是现场图像"时先拉帧算唯一色数, 别猜。

### Orin 全量系统状态上报 (sys 字段)
- `hermes_gateway_mac/orin_sys_status.py` — 采集 CPU% / 负载 / 内存 / GPU(tegrastats或nvidia-smi) / 温度 / 磁盘 / ROS2 节点数 / 关键进程 / 推理服务 / 关节数。
- 心跳 payload 加 `"sys": collect_sys_safe()`（WS 主 + HTTP 兜底都加）; **ECS 两个状态存储都要加 `"sys": {}` 初始化并在 update 里收 `data.get("sys", {})`——zmax_relay.py 和 ws_relay.py 是两份独立存储, 只改一个则另一条路没 sys**。
- 部署后验证: 旧版 Orin 服务还在跑时 `/orin/status` 的 `sys` 为空 {}（正常, 等小芳更新重启推理服务）。

### 现场视频流 (cicd.html 直播窗口)
- 链路: Orin `orin_stream.sh`（每秒抓 D405 帧 → JPEG 质量65 → sshpass scp 覆盖 ECS 网站目录 `orin_realtime.jpg`）→ 网页 `<img src="/orin_realtime.jpg?t=时间戳">` 每 2s 刷新。
- **nginx 缓存坑**: 静态 `.jpg` 正则 location `expires 30d` 会让直播帧被缓存 → 老倪看到"旧图"。修复: 加 `location = /orin_realtime.jpg { add_header Cache-Control "no-store, no-cache, must-revalidate"; expires -1; }`。
- **nginx 正则优先级坑**: `location ~ .*\.(jpg|jpeg|png)$` 正则规则**优先于**前缀 `location /api/relay/` → `/api/relay/cam/latest.jpg` 被 .jpg 正则拦截 404。要用 `location ^~ /api/relay/cam/`（`^~` 前缀匹配优先于所有正则）。加 location 后 curl 公网 + 本机两条路径对比。
- **"黑白格/静态图"排查**: cam_test.html 里硬编码 base64 是 web 的静态测试图, 不是实时流。判断 orin_realtime.jpg 是否真现场: 拉下来看**唯一颜色数**（`np.unique` 全图==1 是纯色测试帧/占位帧）或亮度 std≈0。Orin 流脚本没跑时页面显示的就是旧帧。
- 备用通道（无需 scp）: `POST /api/relay/cam/upload`（JPEG 原始字节）+ `GET /api/relay/cam/latest.jpg` + `GET /api/relay/cam/status`（nginx `^~` 已配）。
- **页面"图像不动"根因 (2026-08-02 实测)**: cicd.html 旧实现从**队列数据包**取图（`pd.frames[0].camera_b64`），但数据包根本没有 camera_b64 字段 → 一直显示"无图像"。直播窗口必须指向**独立帧端点** `<img src="/api/relay/cam/latest.jpg">` + 每 2s `src=?t=Date.now()` 刷新，与数据队列解耦。窗口放大用 `max-height:420px; width:100%; object-fit:contain`。
- **页面并发编辑冲突 (web 和我都改 cicd.html)**: 修改被 web 的并发更新覆盖回旧版（我插入的视频块消失）→ 改完立即 `grep` 验证落盘内容，别假设已生效；与 web 分工前先确认谁负责该文件。
- **先说"已有端点"再谈"开新端点" (2026-08-02 协作实测)**: 小芳报告"没有读快照的通道/peek 拿不到快照"并提议开新端点——但 `/api/relay/cam/latest.jpg` + `/api/relay/cam/status` **早已存在且工作正常**（curl 验证 200 + age_s 0.2s）。协作排查时: 对端报"没通道"先 curl 验证既有端点再回应，别跟着提议新建；真正缺口往往是**前端没接已有端点**（cicd.html 还在读 peek），不是后端缺能力。
- **/api/snapshot/latest 统一快照端点 (2026-08-02 闭环实测)**: 小芳建议"开放 GET /api/snapshot/latest"（她命名）→ 已在 relay 加 `if path == "/api/snapshot/latest" or path == "/snapshot/latest"` 返回归档最新快照 JPEG（200/7KB/age~0.7s 实时 4fps）。cicd.html 直播窗口应接**这个**（或 `/api/relay/cam/latest.jpg`）——两者都返回 318x180 归档快照; 前端 `<img src="/api/snapshot/latest?t="+Date.now()>` 防缓存。**采集数据包的 camera_b64 只有 64x64 缩略图, 不能用于直播/高清训练**（见 lerobot-act-training 黑图陷阱节）。
- **静态模型 URL 的 nginx root 确认 (2026-08-02)**: 模型 scp 到 `/www/wwwroot/datadrive.world/models/` 后, 必须先 `grep root /www/server/panel/vhost/nginx/datadrive.world.conf` 确认**实际站点根**就是该目录（宝塔多站点时可能指向别处 → 404/403）; 文件权限 644; 验证 `curl -I` 看 content-length = 模型大小。公网 HEAD 200 + content-length 87566672 = 静态模型通道可用。
- **PIL 模拟帧文字不渲染 (2026-08-02 实测)**: `ImageDraw.text()` 在无字体文件时静默画不出任何像素（不报错）→ 模拟帧的方向标记/帧号要用**几何图形**（红三角多边形、蓝条、位图条形码），验证时数颜色区域像素而非期待文字。方向验证: 顶部红色锚点像素>50 + 底部蓝色条像素>500 = 方向正常。

### 性能监控铁律 (老倪要求)
- 多机并行干活前先查各端负载: 内存 `free -h` / GPU `nvidia-smi` / 磁盘 `df -h` / 负载 `uptime`; 别超负载极限, 别死机; 干完大任务立即 git push 保存数据。
- ECS 3.5G 内存偏紧（free 常 <200M, 两个 hermes-venv python 占 770M）——84M 上传前先看 free, OOM 崩 relay 后 `bash start.sh` 重启即可。

## relay/nginx 双挂恢复 (2026-08-05 实测: 控制台"采集查询失败红字")
- **症状**: 控制台实时采集状态条红色 "采集查询失败"; `curl -s https://datadrive.world/api/relay/status` 返回空; `curl -sv` 也无输出 → 网络层其实通 (ping 39.102.211.79 29ms, DNS 正常) → 是 ECS 服务层挂了
- **诊断顺序**: `curl -o /dev/null -w "%{http_code}" https://datadrive.world/` (000=服务挂) vs `https://github.com` (200=外网通) → `ping ECS` (通=主机活着) → SSH: `systemctl status nginx` + `ss -tlnp | grep :443` + `ps aux | grep '[z]max_relay'`
- **双挂场景实测**: nginx inactive + relay 无进程 → 先 `systemctl start nginx` 恢复 active，但 **systemd 版 nginx (/usr/sbin/nginx) 加载 /etc/nginx/conf.d，不加载宝塔 vhost (/www/server/panel/vhost/nginx/)** → 443 仍无监听! 必须用宝塔二进制 `/www/server/nginx/sbin/nginx -t && /www/server/nginx/sbin/nginx` 启动（master PID 新起, 443 才监听）
- **relay 重启**: `cd /root/zmax-relay && bash start.sh`（**不要**在 ssh 命令里 `&` 后台跑——会话结束即杀; start.sh 落盘是标准方式）; 验证 `curl -s http://127.0.0.1:39053/status` 本地通 + `curl -s https://datadrive.world/api/relay/status` 公网通
- 全链路恢复判定: 本地 39053 ✓ + 公网 HTTPS ✓ + 首页 200 ✓; 控制台下个 5s 轮询自动变绿（无需重启控制台）
- 老倪反馈红字错误时先查这条链路, 别先怀疑 GUI 代码

## 陷阱（全部踩过，勿重蹈）
1. **pkill 误杀**：`pkill -f zmax_relay.py` 在同一 SSH 命令里会连刚启动的新进程一起杀 → 先 pkill、后单独启动，或直接用 start.sh
2. **SSH 挂起**：`setsid nohup ... &` 直接写在 ssh 命令里会阻塞 60s 超时 → 写 start.sh 落盘，ssh 只执行 `bash start.sh`
3. **阿里云安全组**：ufw allow 不够！新端口(50053/39053)公网不通，ECS 本机走公网 IP 也超时 → 唯一绕过：nginx 反代已有域名 443（`/api/relay/` 模式），别再开新端口
4. **nginx 配置**：sed 插行易破坏 location 块结构 → 先 `cp .bak` + python 精确字符串替换 + `nginx -t` 再 reload
5. **sshpass 变体**：xspace 的 `~/.local/bin/sshpass` 是包装脚本，只支持 `-p`，不支持 `-e`/`-V` → 用 `sshpass -p 'Nix19789' ssh root@39.102.211.79`
6. **本地训练环境**：系统 python3.14 无 torch，必须 `uv sync --python 3.12`（pyproject requires-python >=3.12）
7. **uv sync 慢/镜像缺包**：Fastly CDN 80min+ 下不完 → 试 `UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`，但 aliyun 可能缺包 (num2words → lerobot[all] 无法解析) → 回官方源 `uv sync --python 3.12 --no-default-groups` 装核心, 再 `uv sync --python 3.12 --extra dataset --extra training` 补训练依赖 (缓存命中后很快)。缺 `datasets` 时训练报 `ImportError: 'datasets' is required... pip install 'lerobot[dataset]'`
8. **relay `/ci/validate` 端点别用 subprocess 传 bytes**：`subprocess.run(input=raw_bytes, text=True)` 报 `'bytes' object has no attribute 'encode'` → 端点内直接 `sys.path.insert(0, '/root/zmax-relay')` + `from simulink_ci import run_checks` 内嵌调用, 返回 `rep.to_json()`
9. **relay `/upload` 二进制崩溃 (2026-08-02 实测)**: 直接 `json.loads(raw)` 对二进制 safetensors 抛 **UnicodeDecodeError**（不是 JSONDecodeError！），handler 未捕获 → 整个服务崩溃退出 → nginx 502。修复: 先 `json.loads(raw.decode("utf-8"))` 包在 `except Exception` 里走二进制分支。判断二进制要用 decode 后 try, 别只捕获 JSONDecodeError
10. **大文件上传 nginx 502 超时**: 84M 模型上传默认 proxy 60s 就断 → location 加 `proxy_read_timeout 300s; proxy_send_timeout 300s; proxy_connect_timeout 30s;`（200m body 限制够，超时才是坑）
11. **nginx 反代剥前缀 (2026-08-02 小芳心跳联调实测)**: `location /api/orin/ { proxy_pass http://127.0.0.1:39053/; }` 会剥掉 `/api/orin/` 前缀 → `POST /api/orin/heartbeat` 到达 relay 时是 `/heartbeat`，而 relay 只认 `/orin/heartbeat` → 404/502。修复: relay 端 `if path in ("/orin/heartbeat", "/heartbeat")` 双路径兼容。**同理 `GET /api/orin/status` 会被剥成 `/status`（返回队列信息而非 Orin 状态！）** — 控制台/客户端读 Orin 状态必须用完整路径 `https://datadrive.world/api/relay/orin/status`，别用剥前缀的短路径。新加 nginx location 后先 curl 两条路径验证返回体差异。
12. **relay do_POST 无 else 兜底 → 未知端点 nginx 502**: do_POST 只 if 匹配已知路径、末尾无 else 时，未知端点不写任何响应 → nginx 报 502 Bad Gateway（不是 404）。修复: do_POST 末尾加 `self._send({"error": f"unknown endpoint: {path}"}, 404)`（do_GET 本就有 else，只有 do_POST 缺）。症状排查: curl 返回 502 但 relay 日志无对应 POST 记录 = 端点没匹配上 + 无兜底。
13. **Orin 心跳状态判别**: `/orin/status` 里的 `last_seen` 若长时间不变（如 10:59:52 停留）说明**没有真实心跳进来**——可能是模拟测试残留值或心跳路径不通。真实 Orin 上线时 last_seen 每 5 秒刷新、infer_count 递增。判断\"是否真部署\"看 last_seen 新鲜度，别只看 online:true。
14. **审批窗口 BLOCK**: 前台命令跑超审批窗口会被 BLOCKED（"timed out without user response"）→ 大文件上传/长任务用 `terminal(background=true)` + `notify_on_complete` 跑, 别前台硬等（老倪明确"还用批准么"——部署操作直接干, 后台跑即可）
15. **WS 心跳 vs HTTP 心跳状态源不同**: 控制台读状态有两条路——WS (`wss://datadrive.world/ws` 广播) 和 HTTP (`GET /api/relay/orin/status`)；WS 是实时主通道, HTTP 是轮询兜底。两条路的状态是**两份独立存储**（ws_relay.py 的 ORIN_STATE vs zmax_relay.py 的 ORIN_STATE）——修一条路时另一条不自动同步, 联调时两条都要验
16. **大 JSON 包被误判为二进制 (2026-08-02 联调实测)**: relay `/upload` 原来只读前 4KB 嗅探 JSON——真实采集包(300帧≈97KB) 在 4KB 内无法完整解析 → 落二进制分支存成 `.npz`（丢了 `.json` 语义和 meta.frames）。修复: ①先看 `Content-Type` 含 `json` 直接走 JSON; ②否则读 64KB head 尝试完整解析(≤64MB 才尝试防 OOM); ③否则二进制流式。**另坑**: `is_json = "json" in ctype` 为 True 但 `obj` 只在解析分支里定义 → 跳过解析直接进存储块 → NameError 被 blanket except 吞掉 → 又落二进制。解析要先于分支判断, 确保 `obj` 已绑定。修复后三向验证: 小JSON / 大JSON(300帧) / 84MB模型 都要落对后缀

## 验证闭环
```
# 上传
curl -X POST https://datadrive.world/api/relay/upload -d '{"name":"t","frames":[{"i":1}]}'
# → {"ok": true}
# 拉取（即删）
curl https://datadrive.world/api/relay/latest   # → 数据
curl https://datadrive.world/api/relay/latest   # → {"error":"no data yet"} 404
```

详细部署记录: `references/ecs-relay-deploy.md`
全局数据空间 (dds.db) 更新流程 + 数据闭环统一口径: `references/dds-data-space-update.md`
metaworld 数据源真相 (MT50 截取/nut-on-peg vs 光模块) + 光模块数据生成 (gen_peg_data.py) + rollout 推理修复 (obs dict/stats pad/corner2): `references/metaworld-data-source-and-peg-data.md`
