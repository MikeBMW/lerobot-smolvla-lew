---
name: zmax-cicd
description: Use when Z-MAX 数据闭环/CICD (Orin采集→ECS中转→4060训练ACT→部署Orin).
---

# Z-MAX 数据闭环 CICD (Orin→Mac→ECS→4060→Orin)

三端分工：**静静(我/4060/WSL)** = 训练+推理+GUI+GitHub；**web** = ECS 中转+网站 cicd.html；**小芳** = Mac 采集+Orin 部署。
- **部署目标不只有 Orin (2026-08-06 老倪明确)**: \"训练好的模型, 部署到MAC上, 注意不是orin, 是MAC电脑\" — 仿真/新训模型可能部署到小芳的 Mac (M1, 中转+推理演示机) 而非 Orin。部署前确认目标 (老倪说 MAC 就别推 Orin 监听器), 模型推到 ECS 静态 URL 后通知对应端拉取。

## 链路总览
```
Orin(192.168.23.10:8765 采集) → 小芳Mac(collect_upload.py) → ECS中转 → 4060训练ACT
→ 模型回传ECS → 小芳拉取(cicd_pull_deploy.py) → Orin(:8766 推理, WS+HTTP双心跳) → 控制台
```
- 中转入口: `https://datadrive.world/api/relay/` (nginx 443 反代 → 127.0.0.1:39053)
- WS 状态广播: `wss://datadrive.world/ws` (nginx → 127.0.0.1:8765)
- 版本体系: LeRobot 0.5.2 + Z-MAX v1.x.x，tag+Release 走 GitHub API
- **Release 发布 (gh CLI 未装时用 REST API, 2026-08-02 v1.1.0 实操)**:
  1. 更新版本号: studio.py 窗口标题 + 提交 + `git tag -a vX.Y.Z -m "..."` + `git push origin main --tags`（老 tag 冲突报 rejected 是历史遗留, 新 tag 已推）
  2. 创建 Release: `POST https://api.github.com/repos/MikeBMW/lerobot-smolvla-lew/releases`，header `Authorization: token <token>`（token 从 ~/.git-credentials 正则 `https://([^:]+):([^@]+)@github.com` 提取），body 含 `tag_name/name/body`
  3. 上传附件: `POST https://uploads.github.com/repos/<owner>/<repo>/releases/<release_id>/assets?name=<file>`，`Content-Type: text/html`，--data-binary @file；release_id 先 `GET .../releases/tags/<tag>` 取 `id`

## 端侧部署 VEH.2.26（2026-08-09 老倪"点击端侧部署，部署ACT模型到Orin，通过Mac"）

真实链路 = **静态 URL 覆盖即部署**（`[4060] → [ECS静态URL] → [Orin监听器轮询哈希] → [Orin /models/ 热加载]`），不是容器推送也不是 relay 弹栈：
- **VEH.2.26 下方加「📦 部署模型:」下拉**（`deploy_model_combo`）——读 `models/saved/registry.json` 填充已保存模型，**ACT 优先在首**（`items.sort(key=lambda x: (0 if x[0]=="act" else 1,))`），默认第一个即 ACT；`_deploy_model_to_orin` 模型源优先级：下拉选中 → ckpt_edit → registry 最新 ACT
- **上传 = scp 直传**（nginx 静态目录只读，PUT/POST 都 405）：`sshpass scp model.safetensors root@39.102.211.79:/www/wwwroot/datadrive.world/models/`，写两份——版本化 `act_<ts>.safetensors` + **`act_latest.safetensors`（覆盖即部署约定名，Orin 监听器盯它）**
- **chmod 644 铁律**：scp 保留本地 600 权限 → nginx www 用户读不了 → URL **403**。传完必 `chmod 644`（记忆里"模型=/models/须chmod644"就是这个）
- **验证**：`curl -sI https://datadrive.world/models/act_latest.safetensors` → 200；nginx 支持 Range 断点续传（`curl -r 0-99` 返回 206）——Orin 下载友好
- nginx `/models/` 静态路由已在 datadrive.world.conf（`location ^~ /models/ { root /www/wwwroot/datadrive.world; ... }`，见 Pitfall 5），ECS 侧无需再配
- Orin 侧监听器（小芳）轮询 `act_latest.safetensors` 哈希变化 → 下载 `/models/` + chmod 644 → 热加载推理

## 硬件控制链路 (2026-08-09: 塔灯/摄像头, 本地 WSL 无法直连 Orin)
**关键网络事实**: 本地 WSL 是 172.18.x 网段, Orin 在 **192.168.23.x 局域网** — 本地 `ssh nvidia@192.168.23.10` / `tashan@192.168.23.66` **永远 No route to host**, 不是配置问题。所有硬件控制必须**经 ECS relay → Mac 守护执行** (Mac 192.168.23.1 在 Orin 局域网)。
- **Orin 地址已变更 (2026-08-09 小芳修复, mac 分支 0fda6c27)**: `nvidia@192.168.23.10` (废弃) → **`tashan@192.168.23.66`** (当前)。studio.py/hardware_simulator/zmax_auto_collector/tcp_bridge 共 22 处已改。再遇 Orin 连接失败先 grep 旧 IP。
- **⚠️ 合并 mac 分支的 Orin IP 冲突必须以 mac 分支为准 (2026-08-09 实测, 我合并时反了)**: 合并 `origin/mac` 时 studio.py `_tower_cmd` 冲突——main 分支残留 `nvidia@192.168.23.10` (废弃), mac 分支是 `tashan@192.168.23.66` (当前)。我当时保留了 main 的旧 IP + 注释参考 mac → **错误** (塔灯控制会连不上 Orin)。**规则: 硬件地址类冲突, 以 mac 分支 (小芳维护硬件) 为准, 本技能记录的当前值就是真相; main 的旧值是被搁置的废弃地址, 别用 \"保留 main\" 的直觉**。合并后 grep 确认无旧 IP 残留。
- **塔灯/硬件控制双通道** (`_tower_cmd`): ①本地 SSH 直连 (同网段才可达, WSL 必失败) ②失败自动 `POST /api/relay/command {"cmd": "tower_light <color>"}` → **Mac 守护轮询执行**: `ssh tashan@.66 "source /opt/ros/humble/setup.bash && ROS_DOMAIN_ID=23 ros2 topic pub --once /tower_light/command std_msgs/msg/String '{\"data\":\"<color>\"}'"`。日志必须显示: 本地失败原因 + relay 下发结果 + Mac 执行提示 (用户要求详细反馈, 不许静默吞异常)。
- **⚠️ Mac 守护指令分发坑** (`zmax_auto_collector.py`): 原 `while True: cmd=GET /command; if cmd=="collect": do_cycle()` — **只认 collect, 其他指令静默忽略**。新增分支必须加: `elif cmd.startswith("tower_light")` 和 `elif cmd.startswith("deploy_model")`。
- **⚠️ Mac 守护 BACKEND 地址**: 旧 `http://106.75.239.80:50053` (已废) → **`https://datadrive.world/api/relay`**。改了 studio.py 下发地址但 Mac 守护还轮询旧地址 = 指令"发给空气"。

## 摄像头显示 (2026-08-09: 硬件工具箱参考 cicd.html 方案)
- 方案: **轮询快照端点** `GET /api/snapshot/latest?t=<ts>` (nginx → relay 39053 → archive/snap_*.jpg 最新帧), QLabel 显示 QPixmap + QTimer 1.5s 轮询 (cicd.html 是 100ms, 快照 10s 间隔足够)。连接按钮先探测端点 (200 + image/jpeg) 再启动轮询。
- **⚠️ 快照端点性能坑 (24 万文件)**: 原实现 `sorted(os.listdir(archive))` 全量排序 → 每次请求卡死 (超时/挂起, curl 无响应)。修复: `max(glob.glob(arch_dir/"snap_*.jpg"), key=os.path.basename)` (文件名时间戳递增, 无需排序)。同理 archive 目录大时**禁止全量 listdir+sort**。
- 快照文件在 `/root/zmax-relay/archive/snap_<ts>_<action>.jpg`, 容量控制: 见 disk_guard (曾 505M)。

## 关键端点 (ECS relay zmax_relay.py)
| 端点 | 行为 |
|---|---|
| POST /upload | JSON 包或二进制流式写盘 (自动识别) |
| GET /latest | **弹栈式** — 取走即删，消费方必须立即保存 |
| GET /peek | 只读不删，查看队头 (消费前先确认) |
| GET /status /packages | 队列状态 |
| POST /orin/heartbeat (或 /heartbeat) | Orin 心跳+sys 全量状态 |
| GET /orin/status | 控制台读 Orin 状态 |
| POST /cam/upload, GET /cam/latest.jpg, /cam/status | 现场视频帧 |
| POST /ci/validate | Simulink 模型验证 CI (8项检查) |

## 训练 (4060)
```bash
cd ~/lerobot-smolvla-lew
PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_act_mw_v111.yaml
```
环境: `uv sync --python 3.12 --extra dataset --extra training`；UV 官方源慢时可用阿里云镜像，但缺 num2words 等包会解析失败 → 用 `--no-default-groups` 先装核心再补 extra。详见 `references/lerobot-fork-gotchas.md`。

## 对比与自动迭代
```bash
# 同数据公平对比 (基线 vs 候选) → docs/CICD_COMPARE_*.html/.json
PYTHONPATH=src .venv/bin/python tools/act_compare.py --baseline <ckpt> --candidate <ckpt> --dataset data/metaworld_act --report docs/CICD_COMPARE_auto.json
# 自动迭代: 训练→对比→提升≥5%则部署, 否则改进超参重训
.venv/bin/python tools/auto_iterate.py --max-rounds N
```
- 对比必须同数据+同特征维度（metaworld_act 2D ≠ metaworld_mt50 4D，不可直接比）
- 动作 MSE 对比必须先过 postprocessor 反归一化，否则数量级失真
- 控制台评估页「🔬 基线对比」按钮读取 docs/CICD_COMPARE_*.json

## 联调自动监控 (机器人干活时自动训练)
`tools/live_monitor.py`（后台 daemon，每 30s 轮询 `/status`，SEEN 集合去重）：
- 新包且 `meta.labels` 含**非 IDLE** 动作标签（stage_act 打标: `{"取料": 30}`）→ pull 保存 `data/orin_live/live_*.json` → 后台触发训练
- 纯 IDLE 包跳过（机器人空闲时标签全 IDLE 是正常行为，motion 事件触发型空闲静默）
- 启动: `terminal(background=true) .venv/bin/python tools/live_monitor.py`
- Orin 全量系统状态: `orin_sys_status.py` 采集 CPU/GPU/内存/温度/ROS2/关节 → 心跳 `sys` 字段上报；**zmax_relay.py 和 ws_relay.py 两份 ORIN_STATE 都要加 `sys` 键**，只改一个则另一条路无数据

## 边学边练闭环 (auto_loop.py, 老倪要求"循环起来")
`tools/auto_loop.py` 后台守护：60s 轮询队列 → 新数据包 (frames≥20 且非快照) → 拉取 → `build_orin6d_dataset.py` 重建数据集 → 训练 `config_act_loop.yaml` (独立 output_dir=act_loop) → `upload_model.py` 推回 ECS → 小芳监听器自动部署 Orin → 她继续采集 → 循环。
- **阈值用 20 帧不是 50** — 34 帧的真实包会被 50 阈值跳过
- 训练 output_dir 每次独立，复用已存在目录报 FileExistsError
- 数据闭环节奏: 每轮训练 ~2.5min (2000步)，数据持续累积 (300帧→346→493帧) loss 稳步下降
- **闭环已闭合 (2026-08-02 里程碑)**: 笛卡尔模型 (state 3D TCP位姿 → action 4D 末端速度) 部署 Orin 后真实推理成功 — `orin_real_infer.py 0.6639 -0.0293 0.2935` 输出 (7,4) 动作块 (dx/dy/dz/grip 量级 0.1-0.3 m/s)。**模型传递最终方案 = 静态 URL** (`scp → /www/wwwroot/datadrive.world/models/ + chmod 644` → `https://datadrive.world/models/<name>.safetensors` 直接 GET, 不弹栈不竞争), 详见 lerobot-act-training 模型传递节。闭环验证: `/api/relay/orin/status` 的 infer_count > 0 + 归档快照 age_s < 2。
- **守护训练失败排查顺序 (2026-08-02 实测)**: 数据包 timestamp/frame_index None → `str/str` 除法; 视频帧数<parquet帧数 → FrameTimestampError; frame_index 非全局 → Invalid frame index=N; **timestamp 全局而非 episode 相对 → 双重偏移幽灵超界 (517/1388)** — 见 references/lerobot-dataset-construction.md 帧索引节; ACT delta 未来帧越界 → 每包独立视频; 缓存幽灵 → 清 `~/.cache/huggingface` + `~/.cache/datasets` 整个目录。
- **WS 事件驱动 v2 (2026-08-03)**: auto_loop v2 WS 订阅 `wss://datadrive.world/ws` data_arrived → 毫秒级触发训练 + 60s 轮询兜底 + 断线 5s 重连。ECS 侧: zmax_relay /upload 成功 → notify(:8766) → 广播; ws_relay 加 8766 本地通知口。**依赖 websocket-client** — 缺失时报 `No module named 'websocket'` 退化为纯轮询: `.venv/bin/python -m pip install websocket-client`。单测 6/6 (事件触发/非事件忽略/快照过滤/frames阈值/全链路/并发锁)。
- **容量上限 (2026-08-03, 老倪"控制数据量防磁盘满")**: 单包/缓冲 100M (nginx client_max_body_size 100m + relay MAX_PKG 413 拒绝); `tools/disk_guard.py` 每小时自动清理 (orin_live 限60包/训练产物保留4个/loop_train.log 限5MB/dds_flow 限2万行/tmp 清7天前); ECS logrotate 配 datadrive.world.log + error.log (daily/100M/3份压缩)。ECS 40G 磁盘易满, 重点清 /www/wwwlogs (曾 500M+) 和 /root/zmax-relay/archive (快照 505M)。

## Sim-to-Real 影子模式 (2026-08-05, 老倪"4D action影子模式对比真机")
metaworld 仿真模型与真机模型**双模型并存**, 仿真模型只推理不下发执行 (安全对比):
- 仿真模型: `act_sim_cartesian.safetensors` (state3D末端位置→action4D末端速度+夹爪, metaworld 500帧仿真训练, loss~1.55) — 独立文件名, 勿覆盖真机模型
- 真机模型: `act_cartesian.safetensors` (闭环部署用)
- 流程: 真机TCP位姿(3D)输入 → 仿真模型输出4D action → **影子模式只推理不执行** → 与真机实际动作对比 → 量化 Reality Gap → 回传对比数据 → 迭代训练缩小差距 → 周而复始
- 训练: `PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_act_cartesian.yaml` (metaworld_cartesian 数据, 500帧/5轨迹)
- ⚠️ disk_guard 保留训练产物 4 个 → act_cartesian 等旧训练会被清掉, 静态 URL 上的模型不受影响, 但本地重建需重新训练

## 链路自动化巡检 (2026-08-06, 老倪 @all \"训练,数据闭环,采集,再训练,部署闭环链路要稳定\")
守护体系 = auto_loop (训练闭环) + guard.sh (ECS relay 拉起) + **cron 巡检服务**:
- 脚本: `~/.hermes/scripts/chain_health.py` — 每 30 分钟检查 ① `/api/relay/status` ② `/api/relay/orin/status` (online+model) ③ `/api/snapshot/latest` (200) ④ 本地 `pgrep -f auto_loop.py` ⑤ `df -h /` 磁盘; 结果写 `~/.hermes/cron/output/chain_health.json`, 异常项 (FAIL/DOWN/OFFLINE) 才输出告警 (no_agent 脚本空输出=静默, 有输出才推送)
- 注册: `cronjob action=create no_agent=true schedule='every 30m' script='chain_health.py' deliver='origin'` — **no_agent 模式**: stdout 非空才发, 空输出静默 (看门狗模式)
- 快速手测: `cronjob action=run job_id=<id>` 或直接 `.venv/bin/python ~/.hermes/scripts/chain_health.py`
- 巡检发现 relay 挂 → `ssh root@ECS 'cd /root/zmax-relay && bash start.sh'`; ws_relay 挂 → `start_ws.sh` (guard.sh 只守 zmax_relay, 见上)

## Orin 性能监控 (心跳 sys 字段 → cicd.html 显示)
链路: Orin 心跳 POST /api/orin/heartbeat 带 sys → relay 透传 (zmax_relay.py 已有 `data.get("sys", {})` 支持, 无需改) → GET /orin/status 返回 sys → 前端渲染。采集脚本 `hermes_gateway_mac/orin_sys_status.py` (小芳部署到 Orin ~/.zmax/), tegrastats 不在 PATH 时 GPU fallback 标记 orin-integrated。
- **字段格式规范 (用户明确要求: 全部带单位 + 已用/总量)**:
```json
{"cpu": {"pct": 97.9},
 "gpu": {"pct": 45, "model": "orin-integrated"},   // tegrastats GR3D_FREQ 抓百分比
 "mem": {"pct": 69, "used_gb": 10.5, "total_gb": 15.3},
 "disk": {"pct": 25, "used_gb": 46.2, "total_gb": 182.7, "free_gb": 136.5},  // 空闲必须显示
 "net": {"rx_kbps": 7522, "tx_kbps": 7638, "rx_total_gb": 12.3, "tx_total_gb": 5.1},
 "temp": {"c": 60.4}, "load": [16.45, 15.88, 12.9]}
```
- ⚠️ 用户纠正过两次: GPU 必须百分比 (不能只给 "orin-integrated" 字符串), 磁盘必须显示空闲 G, 内存/带宽必须已用+总量带单位。旧版纯数字格式 (cpu:44.6, disk:21.3) 不合格。
- 带宽是瞬时速率会波动 (采集上传时 MB/s 级正常, 不是异常; 心跳本身 ~KB/s)

## 数据集构建 & 数据生成 (重要, 详见 references/lerobot-dataset-construction.md)
- **LeRobot v3.0 格式硬要求**: parquet 必须 pyarrow float32 fixed-size list (pandas double 会 CastError)；episodes 必备列全 int64；视频必须 `file-000.mp4` 单文件 (不支持 episode_*.mp4)；tasks.parquet 必须有；info.json features 含 index/task_index
- **最隐蔽坑**: `snapshot_download` 会覆盖本地 root (LeRobotDataset 和 Metadata 两处) — 已 patch fork: 本地 info.json 存在时跳过 hub 下载。构建后必须验证 info.json 未被覆盖回 pusht 内容
- **metaworld 无头生成**: `DISPLAY=:0 MUJOCO_GL=glfw` (WSLg X server)；reach-v3 action 是 4D (dx,dy,dz+gripper)；`env.model.site("goal").id` 拿位置
- **跨机器人泛化 (7轴→6轴)**: 不用关节角，用**笛卡尔接口** — state=末端3D位置 + action=4D笛卡尔速度，珞石内部 IK 执行 (有 /robot/tcp_pose)

## 压测
`tools/stress_test.py`：数据链路循环(上传/peek/latest 字节级一致性) + WS 高频心跳 + 并发上传 + 大文件。ECS 仅 3.5GB 内存，84MB 模型上传偶发 OOM → relay 流式写盘已缓解，注意 free 内存。

## 用户偏好 (老倪/大倪)
- 简洁直给，迭代不超 2 轮，说根因不说"试试/应该"
- 自动迭代要"没提升则改进方案重训"，要明确提升路径 (基线→更多数据→更长训练→超参→架构)
- 不跃迁：迭代式开发，保持已有资产，逐步升级
- 别问凭据，自己搞定 (ECS 密码 Nix19789 在记忆里)
- 注意各端性能负载，别死机，及时保存数据 (git push)

## Pitfalls
1. **弹栈队列丢数据**：GET /latest 即删 — 消费方先 /peek 确认再取，取后立刻落盘
2. **二进制 vs JSON 误判**：safetensors 文件头是合法 JSON(以`{`开头)，只读 4KB 判断会误判；用 Content-Type 或 ≤64MB 完整解析尝试，失败走流式
3. **nginx 正则拦截 API**：`location ~ .*\.jpg$` 会拦截 `/api/relay/cam/latest.jpg` → 用 `^~` 前缀匹配提高优先级
4. **nginx 大文件超时**：默认 proxy 60s，84MB 上传需 `proxy_read/send_timeout 300s`
5. **nginx 大模型文件经 PHP 截断 (2026-08-06 实测)**: 网站默认走 `enable-php-80.conf` → `/models/xxx.safetensors` (83MB) 经 PHP 只返回前 1.7~17MB (PHP 内存/超时截断), 且无缓存时 size 不稳定。**修复: 加静态 location 绕过 PHP**:
   ```nginx
   # datadrive.world.conf 的 location = / 之前插入
   location ^~ /models/ {
       root /www/wwwroot/datadrive.world;
       default_type application/octet-stream;
       add_header Cache-Control no-cache;
   }
   ```
   重载: `kill -HUP <nginx master pid>` (宝塔的 nginx -s reload 会因 stream 模块报 emerg, 用面板或 HUP 信号)。**验证必做**: `curl -s -o /tmp/dl.bin <url>` + `md5sum` 与本地比对 (本地 83.5MB 远端必须 83.5MB, 不是 3/12/17MB)。**上传后必查 MD5**: scp 完成后两端 `md5sum` 一致才算部署成功 (曾因只看 HTTP 200 + 1.77MB 误判成功)
5. **pkill 自杀**：`pkill -f xxx.py && nohup python3 xxx.py` 同命令会杀掉新进程 — kill 和 start 分两步
6. **SSH 后台进程随会话退出**：用 setsid+启动脚本 (`start.sh`)，裸 nohup 会死
7. **auto_iterate 正则误匹配**：改 config 的 `steps` 必须 `^steps:` MULTILINE，否则误改 `n_obs_steps`/`n_action_steps` 导致非法配置
8. **多分身协作冲突**：web 和我都可能改 cicd.html — 改前先 grep 现有实现，避免重复插入 (如 live-cam 窗口)
9. **auto_loop 守护静默挂掉 → 队列堆积**：心跳/状态小包 (frames=0) 不被消费堆积在 relay (曾 13 包)。守护进程不在时先重启守护再排查；心跳小包堆积无害 (守护自动跳过), 但 packages 计数会虚高干扰判断
10. **旧 ECS 地址 106.75.239.80 残留**：曾换服务器, 历史脚本/配置里旧 IP 残留 13 处 (zmax_auto_collector/config/dds_cycle/orin_pipeline/collect_upload_npz/zmax_sys1 grpc_host/studio.py) — 新地址 39.102.211.79, 遇到连接失败先 grep 旧 IP
11. **三端版本对齐 (2026-08-08 老倪\"大家怎么版本还差挺大呢, 中版本保持一致\")**: 本地 WSL / GitHub / 远程 GPU 服务器 三处代码必须同 commit。同步流程:
   - 对比: 本地 `git log --oneline -1` + GitHub `git ls-remote origin main | cut -c1-7` + 远程 `ssh <host> 'cd ~/repo && git log --oneline -1'`
   - 远程有未提交改动时 **先 `git stash` 再 `git pull`** (远程的 config 修改如 root=grab6 是训练现场配置, 不该覆盖主仓库 — stash 保留, 主分支干净)
   - 每端提交后立即 `git push`; 远程训练前先 pull 对齐 (远程 79% 磁盘+缺视频数据是另一坑, 见 docker-gpu-training)
11. **Orin sys 格式旧版残留**：心跳还是纯数字 (cpu/mem/disk/gpu/temp/net) = 采集脚本没更新到 v2 (有 used_gb/free_gb/GR3D) — 检查 `grep -c free_gb ~/.zmax/orin_sys_status.py` 应为 2

## 支持文件
- `references/lerobot-fork-gotchas.md` — 本 fork 的 draccus 配置坑、ACT 推理/评估细节
- `references/ecs-relay-patterns.md` — relay 端点设计、弹栈/peek/流式写盘、nginx 反代、WS 心跳模式
- `references/lerobot-dataset-construction.md` — LeRobot v3.0 数据集构建硬要求 (pyarrow float32/episodes列/视频合并/snapshot_download覆盖坑)、metaworld 无头生成、笛卡尔跨机器人泛化、auto_loop 闭环
- `references/optical-factory-scenarios.md` — 光模块工厂三场景原子技能 JSON (插拔/搬运/AOI 工艺参数基准 QSFP-DD、场景 node 语法坑、老倪指标口径)。老倪要求新增/扩展场景或 web 建可视化时用 `flows/scene_skills_3scenarios.json`（已推 GitHub）。
