---
name: zmax-cicd-pipeline
description: "Z-MAX robot policy train/deploy/iterate loop (ACT→ECS→Orin)."
---

# Z-MAX CICD 闭环管线

完整数据闭环: Orin采集 → 小芳Mac → ECS中转 → 静静4060训练 → 模型回传ECS → 小芳拉取 → Orin部署 → 控制台实时状态。

## 链路拓扑

```
Orin(192.168.23.10:8765) → 小芳Mac(192.168.23.1:8769) → ECS中转
ECS: https://datadrive.world/api/relay/ (nginx反代 127.0.0.1:39053)
  ├─ POST /upload           # 数据/模型上传 (流式写盘防OOM)
  ├─ GET  /latest           # 弹栈拉取 (取走即删!)
  ├─ GET  /peek             # 只读查看队头 (不删)
  ├─ GET  /status /packages
  ├─ POST /orin/heartbeat   # Orin心跳上报 (状态反馈源)
  ├─ GET  /orin/status      # 控制台轮询Orin状态
  └─ POST /ci/validate      # Simulink模型验证
WS: wss://datadrive.world/ws (nginx /ws → 127.0.0.1:8765, ws_relay.py 广播)
4060训练 → ECS /upload (84MB模型) → 小芳 cicd_pull_deploy.py 拉取 → Orin :8766推理
```

## 关键命令 (均在 ~/lerobot-smolvla-lew)

```bash
# 训练 (注意: 用 --config_path 下划线, 非 --config-path)
PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_act_mw_v111.yaml

# 基线对比 (同数据公平对比)
PYTHONPATH=src .venv/bin/python tools/act_compare.py \
  --baseline outputs/train/act_metaworld/checkpoints/000300/pretrained_model \
  --candidate outputs/train/act_mw_v111/checkpoints/003000/pretrained_model \
  --dataset data/metaworld_act --report docs/CICD_COMPARE_x.html

# 自动迭代 (训练→对比→<5%自动改进重训→达标部署)
.venv/bin/python tools/auto_iterate.py --max-rounds 1

# 上传模型到ECS (后台, 84MB约40-60s)
.venv/bin/python tools/upload_model.py <model.safetensors>   # 用background=true

# 压力测试
.venv/bin/python tools/stress_test.py
```

## 核心教训 (踩过的坑)

1. **--config_path 是下划线**：这个 fork 的 lerobot_train 用 `--config_path`（parser.py 自定义），不是上游的 `--config-path`。
2. **ACT 配置结构**：`output_dir/job_name` 顶层；`policy.type: act` + `push_to_hub: false` + `repo_id` 在 policy 下；`dataset.repo_id/root`；`optimizer.lr`；顶层 `steps`（不是 num_epochs）。`n_obs_steps` 必须=1（该 fork 不支持多步观测）。
3. **选型须同特征**：对比模型必须同输入特征（同 state 维度/同图像）。metaworld_act=2D state 无图(LeRobotDataset自动补图), metaworld_mt50=4D state 有真图480x480。基线 act_metaworld 是 2D+图。
4. **select_action 返回归一化动作**：需 `make_pre_post_processors` 后 `postprocessor(out)` 反归一化才能与真值比 MSE。`ACTPolicy` 在 `lerobot.policies.act.modeling_act`（不是 policy_act）。`make_pre_post_processors` 从 `lerobot.policies` 导入（不是 lerobot.processors）。policy_cfg 直接用 `policy.config` 即可。
5. **image_features 加载后是 dict 不是 None (2026-08-02 act_compare 实测)**: config.json 里 `image_features: null`, 但 `ACTPolicy.from_pretrained` 加载后 `policy.config.image_features` 变成 `{"observation.image": PolicyFeature(...)}` → select_action 必须喂 `observation.image`, 只喂 state 报 `KeyError: 'observation.image'`。判断喂图: `has_img = bool(imgs is not None and policy.config.image_features)`。**LeRobotDataset 对无图像列的 parquet 会自动生成 observation.image**（metaworld_act 无图列但 ds[0] 有图, 值域 0.235~1.0）→ 评估用 LeRobotDataset 管道加载, 别自己拼 dict。metaworld_mt50 的 parquet 图像列是 `{'bytes': PNG}` dict, LeRobotDataset 直接加载会 CastError（列名/schema 不匹配）→ 用 metaworld_act（2D 无图, 自动补图）。
5. **relay 是弹栈队列**：`/latest` 取走即删！测试/脚本必须先 `GET /latest` 排空到 404 再开始，否则拉到旧包。二进制校验用 `payload[:4]==b'PKG-'`（`PKG-0000-` 第5字符是数字）。
6. **ECS 仅 3.5GB 内存**：84MB 上传易 OOM 崩 relay。已改流式分块写盘(64KB chunks)，仍偶发——上传用 background 进程 + 崩后 `bash /root/zmax-relay/start.sh` 重启。
7. **nginx 反代**：ECS 安全组只开 80/443，内部端口(39053/8765)必须走 nginx 反代 (`/api/relay/`、`/api/orin/`、`/ws`)；大文件加 `proxy_read_timeout 300s`；HTTP handler 未知端点必须有 else 兜底否则 nginx 502。
8. **SSH 后台进程**：`nohup ... &` 随 SSH 会话退出被杀，必须 `setsid nohup ... < /dev/null &` 或写 start.sh。
9. **sshpass**: `sshpass -p 'Nix19789' ssh -o StrictHostKeyChecking=no root@39.102.211.79`（本机可用；resolute 装不上）。
10. **relay JSON/二进制判定 (2026-08-02 修复)**：旧版只读前4KB尝试 json.loads 判 JSON → 大 JSON 采集包(>4KB)误判为二进制存成 .npz。新版：Content-Type 含 `json` 或完整解析成功(≤64MB 才尝试, 防OOM) → 存 .json；否则流式写盘二进制。**坑**: `ctype` 含 json 时若直接 `is_json=True` 但 obj 未定义 → NameError，判定和解析必须同一分支。safetensors 头是合法 JSON 但 84MB>64MB 限制 → 正确走二进制流式。
11. **快照自动归档 (2026-08-02)**：Orin 快照包 (`source=orin_snapshot` / 含 `snapshot_b64`，frames=0) 每 30s~1s 一个，会污染训练队列堆积数千包。relay /upload 收到即解码归档到 `/root/zmax-relay/archive/snap_<ts>_<action>.jpg` + 同名 .json 元数据(current_state/all_states/action)，不进 data/ 队列。**peek 归档兜底**：队列空时 peek 返回最新归档快照(current_state+snapshot_b64)，页面状态机/图像靠它实时更新。清理残留：遍历 data/*.json 删 source==orin_snapshot。
12. **cam 视频流端点**：`GET /cam/latest.jpg`（归档快照优先, 非 cam/ 实时推帧优先——cam/ 里可能是模拟推帧残留）、`GET /cam/status`、`POST /cam/upload`（Orin 推帧）。**nginx `^~ /api/relay/cam/` 必须放 .jpg 静态正则之前或用 `^~`**（`location ~ .*\.jpg$` 会先拦截带 .jpg 的请求导致 404）。实时帧加 `Cache-Control: no-store` 防浏览器缓存旧图。
13. **auto_iterate 改进正则坑**：`sed/regex 改 steps: \d+` 会误匹配 policy 下 `n_obs_steps: 1`/`n_action_steps: 7` 改成 3000 → 配置非法训练失败。必须行首锚定只改顶层 `^steps:`。
14. **act_compare JSON 路径**：JSON 输出必须 `Path(args.report).with_suffix(".json")` 跟随 --report，别硬编码版本名（auto_iterate 读不到会报对比失败）。
15. **微调 lr 坑 (2026-08-02)**：从基础模型继续训练 (`policy.pretrained_path`) 用 lr=5e-5 会破坏基础权重 → MSE 退化(-8.43%, 13052 vs 12038)。改进用 lr=1e-5 保护基础权重。对比必须同数据同特征才有意义。
16. **7电机数据 vs 实机 (2026-08-02 老倪\"7个电机的\"→小芳实测澄清)**：metaworld (Sawyer) 是 **7轴**，但产线实机是 **6 关节 SR5** (`/sim_joint_trajectory` 6D关节轨迹, `/robot/tcp_pose` 笛卡尔位姿) — 训练维度必须先经小芳确认实机 DOF/控制器接口再定，别信任务描述里的\"7电机\"。**真机 6D 数据在 `data/orin_live/*.json`** (n_joint=6, n_action=6, 带 stage_act 标签如\"料盘识别\"；`tools/build_orin6d_dataset.py` 转 LeRobot 格式 `data/orin_6d/`, 266帧/4轨迹, action 范围 ±2.8~4 真实运动)。同 repo_id 加载 6D 数据也踩全套 LeRobot 格式坑 (episodes 残留/float32/视频 file-000 合并), 见 lerobot-act-training。
17. **笛卡尔接口模型 (7轴数据泛化6轴实机, 2026-08-02)**：模型输出 `state=末端3D位置(x,y,z)` + `action=4D末端速度(dx,dy,dz+gripper)`，部署到珞石经内部 IK 转 6D 关节。`tools/gen_metaworld_data.py` 改 state=site_xpos[endEffector] → `data/metaworld_cartesian` (state3D/action4D), `config_act_cartesian.yaml` 训练 (2000步 loss 1.555)。Orin 推理服务喂 TCP 位姿前3维做对比。详见 lerobot-act-training「跨机器人泛化」节。**本地 LeRobot v3.0 数据集构建全套坑（hub覆盖/parquet float32/frame_index全局化/视频帧数一致/ACT delta超界）见 zmax-data-pipeline 的 `references/lerobot-dataset-format.md`**。
18. **边学边练闭环守护 `tools/auto_loop.py` (2026-08-02 老倪"边学边练循环起来")**：60s 轮询 ECS 队列 → 检测非快照数据 (frames≥50) → 拉取存 `data/orin_live/auto_*.json` → 重建数据集 → 快速训练 (2000步) → 自动上传模型回 ECS → 小芳拉取部署 Orin → 她再采集 → 循环。运行: `.venv/bin/python tools/auto_loop.py` (background=true, 长期守护)。**Orin 心跳在线但 infer_count=0 + 队列模型没人拉 = 小芳拉取守护停了** (本会话 19:05 模型卡队列 25 分钟), 链路本身正常。
19. **模型传递最终方案 = 静态路径 (2026-08-02)**：弹栈队列 + 两端竞争消费会抢包丢模型。scp 到 ECS 网站目录 `models/` + `chmod 644`（600=403），对端 `curl https://datadrive.world/models/<name>.safetensors` 一次到位，永久无竞争。
20. **WS 事件驱动闭环 (2026-08-03, auto_loop v2)**：从 60s 轮询升级为毫秒级触发——ECS `zmax_relay.py` /upload 成功 → notify(:8766) 广播 `data_arrived`；`ws_relay.py` 加 8766 本地通知口广播 latest/frames/ts，新客户端接入即推当前状态；auto_loop v2 WS 订阅 + 事件立即触发训练 + **60s 轮询兜底** + **断线 5s 自动重连**。验证: 上传 25 帧 → WS 毫秒触发 → 训练 → 推回。单测覆盖事件触发/非事件忽略/快照过滤/frames 阈值/并发锁。
21. **数据量上限控制 (2026-08-03 老倪"上线100M/不要把磁盘充满")**：① nginx `client_max_body_size 200m→100m`（comfyui 500m 保留）；② relay 加 `MAX_PKG = 100*1024*1024` 单包校验，超限返回 413；③ `tools/disk_guard.py` 容量守卫（每小时）：orin_live 保留最近60包、outputs/train 保留最近4个、loop_train.log 截断5MB、`dds_flow` 序列保留2万行、/tmp 清7天前。训练产物每个 500MB-1GB，不清理会撑满磁盘。
22. **水流式全局数据空间 (2026-08-03, 老倪"像水流一样刷写DDS")**：zmax-website 双分层——**主数据层**(稳定, 变化慢): `m_workpiece/m_equipment/m_station/m_process/m_model` 表（init_master_data.py 种子）; **流水层**(实时, 每10s): `dds_flow`(时间序列+flow_rate) + `dds_node_state`(当前状态)。`waterflow_dds.py` 守护探测7节点(采集/上传/训练/模型URL/部署/推理/控制台)真实状态→刷写, 流水引用主数据ID（如推理节点带 `模型:MD-ACT6D-v3`）无冗余可追溯。设计文档 `zmax-website/docs/MASTER-DATA-SPACE.md`。
23. **珞石 SDK 只读体检 (2026-08-03)**：`connectToRobot(remoteIP, localIP)`（**不带 ec**）→ 查询 `robotInfo(ec_dict)`/`powerState(ec_dict)`（**ec 必须是 dict 不是 PyErrorCode 对象**）→ 端口 6666 TCP，与产线 robot_driver 共存不踢线。实测型号 **XMS5-R800-W4G3B4C** 固件 3.2.1 6关节（非 SR5-C 命名，以实测为准）→ 更新 `m_equipment` 主数据。报警查询 queryEventInfo 需时间范围参数。只读不干扰产线。
24. **旧 ECS IP 清理 (2026-08-03)**：历史遗留 IP `106.75.239.80` 已全仓库替换为新 ECS `39.102.211.79`（zmax_auto_collector/dds_cycle/orin_pipeline/collect_upload_npz/ib_robot_config/zmax_sys1 grpc_host/studio.py/data_closed_loop）。hermes_gateway_mac/ 本来就全是 datadrive.world 新地址。
25. **Orin 性能监控 sys 字段 (2026-08-04, cicd.html 显示)**：链路 Orin 心跳 /heartbeat 带 `sys` → relay 透传 → `/orin/status` → cicd.html。采集脚本 `hermes_gateway_mac/orin_sys_status.py`（tegrastats GR3D / nvidia-smi / /proc 双通道）。**用户格式铁律 (老倪)**: GPU 必须百分比 `{"pct":45}`（模型名 `orin-integrated` 被否）；带宽必须速率+累计 `rx_kbps/tx_kbps/rx_total_gb/tx_total_gb`（单值被否）；内存/磁盘必须已用+总量+单位 `used_gb/total_gb/free_gb`+pct（纯数字被否）；温度 `{"c":60.4}`。带宽波动=采集/推流活跃正常信号。
26. **Sim-to-Real 影子模式 (2026-08-05, 老倪"4D action影子模式与真机对比")**：metaworld 仿真模型独立存 `act_sim_cartesian.safetensors`（state3D→action4D, 与真机 act_cartesian 分开）；影子=只推理不下发执行, 4D action 对比真机实际动作量化 Reality Gap；报告回传 `source:"orin_shadow", type:"shadow_report"`；⚠️ shadow 报告 act_dim/state_dim 必须=4/3, 若=2 是 Orin 加载了旧 2D pusht 模型, 对比无意义; auto_loop 不消费 shadow_report(frames=0), 堆积定期清。
27. **快照归档目录膨胀卡死 snapshot 端点 (2026-08-06, cicd.html 无图像排查)**: archive 目录累积 **1170 万文件 (1.7GB)** → snapshot 端点 `sorted(glob.glob("/root/zmax-relay/archive/snap_*.jpg"))` 全目录扫描**卡死超时** → `/api/snapshot/latest` 返回 502/HTTP 000 → cicd.html 实时画面空白。**区分单端点 vs 全 relay 挂**: `/orin/status` 仍 200 (不 glob archive) 但 snapshot 000 = 单端点卡死。**排查顺序**: ① 公网 curl 000/502 ② ECS 本机 `curl http://127.0.0.1:39053/api/snapshot/latest` 也 000 (排除公网) + orin/status 200 (relay 活着) ③ `ls archive | wc -l` 百万级=根因。**修复三件套**: ① `cd archive && ls -t | tail -n +100 | xargs -r rm -f` 清到约100个 ② relay 快照端点 glob 全扫 → `os.listdir` 过滤 .jpg (只读最新, 不卡) ③ 写归档后自动 unlink 保留最近 300 个 (防再累积)。快照 1s/帧自动归档, 不设上限必然再爆。**relay 进程守护**: `guard.sh` 每 60s `ss -tln | grep -q 39053` 挂了自动 `bash start.sh`, nohup 拉起 — relay 曾多次崩溃/挂死, 守护是标配。验证: `curl -o x.jpg -w '%{http_code} %{size_download}B %{content_type}' .../api/snapshot/latest` → 200 + image/jpeg + ~11KB。

## rollout 视频生成/修复 (2026-08-07 七模型对比实测)

**正确命令** (GUI 的 _run_rollouts 同款, 视角才能看到插槽):
```bash
.venv/bin/python tools/rollout_video.py --policy <p> --steps 60 \
  --task peg-insert-side-v3 --camera corner2 --rotate-ccw \
  --out reports/rollout_final_<p>
```
- **`--camera corner2` 是硬性要求**: 默认 `corner` 视角看不到插槽 (老倪否过两次: 先转 180° 没用, 是视角问题)。`--rotate-ccw` = rot90 k=2 (180°)。MLP/专家的现成视频在 `rollout_mlp/`、`rollout_expert_full/` (不是 rollout_final_*)。
- **V3 环境 obs 是 dict** (`observation.state`/`observation.image`): `np.asarray(obs)` → 0 维对象数组 → state 全零 → 所有模型推理异常/动作≈0。必须 `obs.get("observation.state")` 解包。
- **stats 归一化维度陷阱**: checkpoint 的 stats 可能是旧 3D 而 state 39D → `(39,)-(3,)` 广播异常。修: 维度不足 `np.pad` 补零 + **pad 后 `+1e-6` 防除 0 NaN** (动作全 NaN 视频仍生成但无意义)。
- **ACT 39D 完整观测 = robot(3)+env(36)**: ACTPolicy 期望 `observation.environment_state`, 从 `policy.model.encoder_env_state_input_proj.weight.shape[1]` 推断拆分 (别依赖 config 的 input_features — 可能没有该键)。
- `load_policy()` 返回 **(policy, label) 元组**, 用 `[0]`。
- **视频"动没动"快速验证** (帧间均差, 无渲染也能判): 首末帧灰度均差 >1.5=动 / 0.8-1.5=微弱 / <0.8=没动; 动作均值 `np.abs(np.load(actions.npy)).mean()` >0.05 才算有动作。

**插拔演示视频 gen_insert_video.py 模型加载 5 坑 (2026-08-12 实测, 老倪"生成视频慢又不生成")**:
- **① 训练产物 root 600 权限 → 读不了**: docker 训练输出 `outputs/train/left_right_*/checkpoints/` 是 root:root `-rw-------`, 普通用户 python 打开 FileNotFoundError/权限拒绝 → **`sudo -n chmod -R 644 <dir>` + 目录 755**(记忆铁律"模型 chmod644"每轮训练后必查, 又踩了)
- **② 脚本写死旧模型文件**: 原写死 `outputs/rl_peg/full_pipeline.pt`(旧 RL 管线) → 生成的是旧模型视频; 改 `_load_brain()` 按 **mtime 排序** 找最新 `outputs/train/left_right_*/checkpoints/last/pretrained_model/model.pt`(⚠️ 字母序 sorted(reverse=True) 会把 `left_right_std` 排到时间戳目录前 — 必须 `key=os.path.getmtime`)
- **③ RightBrainWM 网络结构变体**: 训练用的 `modeling_left_right.py` 版右脑 = {enc, pred_next, contact_head} 返回 **2 值** (next_obs, contact); `tools/train_full_pipeline.py` 版多 **align_head** 返回 3 值 — 加载 model.pt 用错类 = `Missing key(s): align_head.weight`; 调用处解包数也要对 (3 值解包→2 值)
- **④ 归一化参数位置**: 新 checkpoint 无 xm/xs/ym/ys 字段 — 在 `left_right_preprocessor_step_3_normalizer_processor.safetensors`(`observation.state.mean/std` 标量整段) + `left_right_postprocessor_step_0_unnormalizer_processor.safetensors`(`action.mean/std`); safetensors 键是 lerobot 标准 (action.count/observation.state.mean/... 每键 (1,))
- **⑤ 前向 device 匹配**: 模型 `.to(DEVICE)`(cuda), 推理输入 obs 也要 `.to(DEVICE)` — 忘了报 "mat1 is on cpu, different from other tensors on cuda"
- 性能: GPU 空闲时 6000 次 seed 试跑 48s 出片; 慢=CPU(检查 nvidia-smi 是否被训练占)

**视频对话框三个坑 (simulink_scope.py, 全修过)**:
- **打开"闪一下再次打开"**: `_check_newer_ckpt` 把残缺曲线 (中断训练残留, 0-50 点但 ts 新) 误判为"新 checkpoint" → 每次打开触发重新生成。修: 曲线点 <100 不算新。
- **白屏**: 对话框未显示时 `lab.size()=0` → `scaled(0,0)` 空白。修: 尺寸有效才缩放, 否则 setPixmap 原图。
- **模型名标题飘到上面窗口**: 标题在视频框上方视觉归属上一行。修: QGridLayout 同 cell 叠加到视频框左下角 + 半透明底。
- **on_infer_video 触发前检查漏 expert 目录映射**: expert_mlp/expert_policy 的帧在 rollout_mlp/rollout_expert_full → 触发检查必须带同款 `_dir_map`, 否则误判无帧 → 重新生成失败 → "视频没了"。

## 光模块训练: MLP 蒸馏 > ACT 长训 (2026-08-08 实测, 老倪"要能插入")
- ACT 光模块数据 4000 步: loss 64→0.585 收敛但 rollout **0/5** (销钉没抬起 — 长程动作链没学会)
- **MLP 蒸馏** (distill_expert.py: 官方专家 300 eps 采样 + 15 epochs, loss 0.507): 插入 **2/5 (40%)**, 最小孔距 **0.011m**, 5/5 全抬起
- **教训**: 长程精确操作 (光模块) 数据不足时, **从专家策略蒸馏小模型 (纯 39D state→4D action) 立竿见影, 远胜长训大模型** — 光模块任务优先方案: 蒸馏 > 多训
- **ExpertMLP 加载链 3 坑** (rollout_video.py + rollout_peg_check.py 两处都要):
  1. 曲线 ckpt 指向 `.pt` 单文件**非目录** → isdir False → FileNotFoundError; 修: `if policy=="expert_mlp" and os.path.isfile(base_dir)` 特判 + importlib 加载 distill_expert.py → ExpertMLP(obs_dim, act_dim) → load_state_dict(data["model"])
  2. **必须 `pol.state_dim = pol.obs_dim`** — 否则 st_dim 推断 `getattr(policy,"state_dim",2)`=2 → forward 1x2 vs 39x512 崩 → 动作 0.0
  3. 无 select_action/_cond → 加 `elif hasattr(policy,"obs_dim") and not hasattr(policy,"model"): pred=policy(batch["observation.state"])`; argparse `--policy choices` 加 expert_mlp/expert_policy
- 验证脚本跑 torch 依赖代码必须 `.venv/bin/python` (系统 python3 无 torch)

## 模型引擎容器化 (2026-08-08, 远程 GPU Docker 训练)

> **2026-08-09 远程 4090 训练链全链路修复实录 (cuDNN崩溃/output_dir冲突/Model Zoo远程误判/自动拉回/静态URL部署) 见 `references/20260809-remote-4090-train-chain.md`** — 新 GPU 4090 @223.109.239.30:15032, 嵌套凭据 json, 训练入口禁用 cuDNN, docker logs 拉日志, output_dir 时间戳 sed, 端侧部署静态 URL 覆盖即部署。**同文件另含: 仿真渲染无头化 (容器内 rollout 需 xvfb + zmax-std:render 镜像 + MUJOCO_GL=egl)、部署链路详细反馈铁律 (分块上传百分比 + ECS 连通探测 + chmod 644 必查)**


模型引擎 = 训练中枢: GPU 选择 (本地 4060 / 远程 V100) → 远程训练走 **Docker 容器** (`zmax-train:latest` 镜像, pytorch 2.2.0-cuda12.1 + lerobot)。完整配方/命令/坑见 **`references/remote-gpu-docker.md`**。核心铁律:

1. **免 nvidia-container-toolkit**: 服务器装不上 toolkit (没 curl/源 404/CDN 403) → `docker run --device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm -v libcuda.so.1:...` 手动 GPU 透传, torch.cuda 实测可用。
2. **Docker Hub 国内加速必须配** (docker.1ms.run / docker.m.daocloud.io), 否则拉 pytorch 基础层失败。
3. **镜像 Python 3.10 vs lerobot pyproject >=3.12** → Dockerfile 加 `--ignore-requires-python`; **必须全依赖安装** (`--no-deps` 漏 termcolor/tensorboard → 训练秒崩)。
4. **远程训练命令 = `python -m lerobot.scripts.lerobot_train`** (pip 包, 仓库无 lerobot/ 目录); 服务器无 `python` 只有 `python3`。
5. **防假阳性**: 提交后查 `docker ps --filter name=zmax_train` + log 无 Error; `grep [l]erobot_train` 会匹配 ssh shell 自身。
6. **docker restart 杀 build**: build 期间别重启 docker; 构建用本地后台 ssh (notify) 保持连接。
7. SSH 连接: `sshpass -p ... ssh -o Port=24424` (**-p 被 sshpass 吞**); 服务器重启会改端口/密码 (24212→24424), Connection refused 持续 = 问老倪要新凭据。
8. **PEP695 泛型大坑 (2026-08-08 容器秒退根因)**: lerobot 代码用 Python 3.12 泛型语法 (`def f[T: X]` / `class C[TInput,TOutput]`) — **镜像 Python 3.10 解析崩 SyntaxError** (`io_utils.py:93` → `pipeline.py:254` → `streaming_dataset.py:58` 逐个暴露)。修源码可行 (`def f[T]` 去泛型 + 类泛型改传统 `T = TypeVar("T")` + **所有 `Class[T]` 调用处去下标** — 注意跨行/嵌套泛型 `\[[^\]]*\]` 会截断, 用 `\[[\s\S]*?\]` 仍可能吃嵌套 `]` 留残留), 但**修不完** (3.12 特性散落 200+ 文件 `dict[str]`/`X|None` 虽 3.10 兼容, 真泛型 5+ 处) → **最终方案 = venv Python 3.12 快路径, 别在容器 3.10 上死磕**。
9. **venv 3.12 快路径 (容器失败后的主线)**: `/root/lerobot-venv` (deadsnakes python3.12) + `pip install --no-deps -e .` (**必须 --no-deps** — 带依赖会解析拉 torch 2.11 覆盖已装的 2.2.2/2.3.0 且不完整) + **逐个补缺包** (datasets/av/accelerate/termcolor/tensorboard — `--no-deps` 漏一堆, 报错迭代补) + `torch==2.3.0 --index-url .../cu118` (3.12+V100 sm_70 确定支持)。远程直跑: `/root/lerobot-venv/bin/python3 -u -m lerobot.scripts.lerobot_train --config_path <cfg>`。
10. **--config_path 是下划线** (fork 的 parser.py 自定义, 非上游 `--config-path` — 用短横线报 `unrecognized arguments`) — 本地 GUI / 远程 / 容器命令全要下划线。
11. **GUI 子进程输出卡住 = python 块缓冲 + tqdm \r**: 非 tty 下 stdout 块缓冲 (攒 4K 才输出) → 命令加 `-u`; tqdm 用 `\r` 刷新不换行, `for line in p.stdout` 永远等不到 `\n` → **块读 `p.stdout.read(4096)` 按 `\r`/`\n` 分行**, 进度条实时进日志 (老倪铁律: 终端信息不简化, 每行完整打印截 600)。
12. **训练队列轮询防误判**: pgrep 检查训练进程时, on_train 数据准备有延迟 (进程未起) → 秒判"完成"秒推进假象。**启动后 45s 窗口内不判完成 + 进程在时重置窗口**。
13. **远程自主串行训练脚本模式**: bash 循环 `run_one POL CFG DATA` — 先 `sed -i "s|^  root: .*|  root: $DATA|"` 统一数据 (远程只传 1-2 个数据集, config 的 root 五花八门) + 无 config 的模型跳过 (vla_touch) + 特殊模型用独立脚本 (awe_zflow=train_awe_zflow.py); 监控 cron 查状态要**进程优先** (旧 log 的 ALL_DONE 会误判完成)。
14. **模型引擎自动连接**: GUI 启动 3s `QTimer.singleShot` 自动 `_connect_gpu` (凭据 ~/.zmax_ssh.json 预填) — 免手动点连接按钮 (老倪: "模型引擎应该自动连接")。

## 三处版本一致性 (老倪"大家怎么版本还差挺大呢, 中版本保持一致" @all, 2026-08-08)
版本三处必须对齐: **本地(4060 WSL) / GitHub(main) / 远程服务器(V100)**。每次推代码后检查:

```bash
# ① 本地 + GitHub 对比
cd ~/lerobot-smolvla-lew && git log --oneline -1
git ls-remote origin main | cut -c1-7   # GitHub 最新 commit
# ② 远程服务器对比
sshpass -p 'da9eo7yo' ssh -o Port=24424 root@223.109.239.36 \
  'cd ~/lerobot-smolvla-lew && git log --oneline -1'
```

**远程落后时的同步** (远程常有本地修改, 直接 pull 会冲突):
```bash
git stash                        # 先藏本地修改 (训练 config root 等)
git pull -q origin main          # 对齐主仓库
# 本地修改仍在 stash@{0}, 需用时 git stash pop
```
- **远程服务器的本地修改不要 push 回主仓库** (config 的 root 指向 grab6 等是远程特有) — stash 保留即可。
- 远程改 config 用 `sed -i "s|^  root: .*|  root: data/xxx|"` 运行时改, 不 commit。
- 训练前先 `git pull` 保证远程代码 = 最新实验代码 (否则训的是旧版模型逻辑)。

## 版本发布流程

```bash
# 更新版本号 studio.py 标题 → commit → tag → GitHub API Release
git tag -a vX.Y.Z -m "..."
git push origin main --tags
python3 /tmp/create_release.py   # API 方式创建 Release (gh CLI 未装)
# 附件: curl -X POST .../releases/$ID/assets?name=REPORT.html --data-binary @file
```

## 相关文件

- **Z700 模型整体 docker 部署到 Mac M1 (2026-08-12)**: 3 模型构成(YOLO 22MB + model.pt 2.5MB 键 left/right/obs_dim/act_dim, 双脑一体) + `docker/z700_infer/` 镜像三件套(Dockerfile arm64v8/python + infer_service.py + modeling.py) + 部署链路(模型包 25MB 走 ECS relay, 镜像 Mac 本地构建, /detect /predict 接口抽象供 Orin 复用) — **详见 `references/z700-docker-mac-deploy.md`**
- `tools/cicd_pipeline.py` — 三阶段渐进式训练管线 (S1 MetaWorld仿真→S2零样本测试→S3 Orin微调, 自动流转 run/stage/test, 状态 docs/PIPELINE_STATE.json, 详见 lerobot-act-training)
- `tools/npz_to_lerobot.py` — npz→LeRobotDataset v3.0 转换器 (PyAV h264 视频, 真实特征维度; 假 meta 模板=假训练, 详见 lerobot-act-training)
- `tools/relay_train.py` — 拉取JSON训练数据转npz (≠ 部署模型用 cicd_pull_deploy)
- `tools/cicd_deploy.py` — 4060端推送模型
- `tools/upload_model.py` — 上传单个模型文件
- `tools/act_compare.py` — 基线对比评估
- `tools/auto_iterate.py` — 自动迭代循环
- `tools/stress_test.py` — 全链路压测
- `tools/gen_cicd_report.py` — CICD HTML报告
- `tools/live_monitor.py` — 联调监控 (30s轮询队列, 过滤快照, 检测stage_act非IDLE标签→自动拉取训练)
- `tools/data_sync.py` — 数据同步 (ECS→本地增量拉取归档/队列, 达标数据触发训练)
- `tools/auto_loop.py` — 边学边练闭环守护 (60s轮询→拉取→训练→推回ECS→Orin升级循环; v2=WS事件驱动+60s兜底+5s重连)
- `tools/disk_guard.py` — 容量守卫 (每小时: orin_live 60包/训练4个/log 5MB/dds_flow 2万行/tmp 7天)
- `tools/build_orin6d_dataset.py` — orin_live JSON → LeRobot 6D 数据集 (state6D/action6D)
- `tools/cam_push_sim.py` — 模拟推帧服务 (验证直播链路, 图形方向锚点不依赖字体)
- `tools/gui/simulink_scope.py` — Simulink Scope示波器 (ScopeCompareDialog: 加载基础+微调模型→同一测试输入→动作曲线叠加对比, 绿色虚线=专家真值; 导出PNG; 工具栏「🖥 Scope示波器」按钮在 simulink_module.py 的 show_scope)
- `hermes_gateway_mac/cicd_pull_deploy.py` — 小芳端拉取+部署Orin
- `hermes_gateway_mac/orin_infer_service.py` — Orin推理服务(:8766, WS+HTTP心跳)
- `hermes_gateway_mac/collect_upload.py` — 小芳端采集上传(Orin 10秒→打包JSON→推ECS, `--seconds N` / `--loop`)
- `/root/zmax-relay/zmax_relay.py` + `ws_relay.py` — ECS端服务
