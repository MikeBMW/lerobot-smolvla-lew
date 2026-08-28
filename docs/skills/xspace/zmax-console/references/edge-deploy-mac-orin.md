# 端侧部署链路 (2026-08-09 会话沉淀)

VEH.2.31「📥 推送到 Orin」= 模型下载按钮 (端侧部署模式高亮后才可点, `_ct_pick` 里 `setEnabled(key=="deploy")`, 初始 False)。
链路: [4060] 模型 safetensors → ECS 静态 URL → Mac 守护轮询 → 构建/加载 arm64 容器 → 部署 Orin。
所有 IP/凭据/端点均为实测。

## 1. ECS 静态 URL 部署 (datadrive.world/models/ 覆盖即部署)
- 站点: datadrive.world (宝塔, root=/www/wwwroot/datadrive.world), nginx 已配 `location ^~ /models/` 静态路由 (add_header Cache-Control no-cache)。
- 上传方式: **scp 直传 ECS** `root@39.102.211.79` 到 `/www/wwwroot/datadrive.world/models/`。**PUT/POST 到 nginx 静态目录 = 405** (只读), 别试。
- 命名约定: 版本化 `act_<ts>.safetensors` + `act_latest.safetensors` (覆盖即部署, Orin/Mac 轮询 latest)。
- **chmod 644 铁律**: scp 保留本地 600 权限 → nginx www 读不了 → URL 403。上传后必须 `chmod 644`。
- 断点续传: nginx 支持 Range (206), Orin/Mac 下载友好。
- URL 验证: `curl -sI https://datadrive.world/models/act_latest.safetensors` 应 200。

## 2. 分块上传带百分比 (用户铁律: 详细反馈, "我要详细反馈")
- scp 87MB 静默 2 分钟 = "没反应" (用户强烈不满)。必须逐块反馈。
- 方案: 8MB 块 + `sshpass ssh 'cat >> <models_dir>/<name>'` 管道, 每 5% 打 `百分比 (KB/KB) · KB/s`。
- **先 `rm -f` 远程同名文件** (cat >> 追加会残留旧内容重复)。
- 完整链路日志顺序 (用户验收标准): 模型源路径+大小 → ECS relay /status 在线 → SSH_OK 探测 → 分块百分比 → 已上传 → chmod 644 → URL HEAD 200 → Mac 指令下发 → Orin 状态。

## 3. ECS relay /command — Mac 中转指令 (Orin 局域网不可直连的钥匙)
- Orin 在 192.168.23.x 局域网 (192.168.23.10), WSL 本地是 172.18.x — **不同网段, 本地 ssh 直连永远 No route to host**。控制 Orin 必须经中转。
- relay: `https://datadrive.world/api/relay` (ECS 39053, zmax_relay.py):
  - `GET /status` → 在线/队列包数
  - `POST /command` `{"cmd": "..."}` → 写入 command.json, **Mac 守护轮询执行** (Mac 192.168.23.1 同 Orin 网段, 可达)
  - `GET /orin/status` → Orin 在线/模型/推理次数 (心跳上报)
- 部署指令示例: `deploy_model act act_<ts>.safetensors` (Mac: git clone 仓库 → docker build --target infer (arm64 原生) → 拉模型)。

## 4. 塔灯控制双通道 (VEH.3.16 红灯"之前可以现在不行"根因)
- 旧 `_tower_cmd`: ssh nvidia@192.168.23.10 本地直连 → 不同网段 No route to host → 异常被 except 吞 → **按钮看似无反应** (Orin 实际在线, relay 心跳正常)。
- 修复: ① 本地直连 (returncode==0 才成功) ② 失败自动 POST relay /command `tower_light <color>` → Mac ssh Orin → `ros2 topic pub --once /tower_light/command std_msgs/msg/String`。
- 教训: 硬件控制按钮必须**双通道 + 明确失败日志**, 异常别吞 (用户以为按钮坏了, 实际是网络拓扑)。

## 5. 仓库根路径 dirname 层数坑 (Tools/gui 特有)
- studio.py 在 `tools/gui/` 下 → repo root 需 **3 层** `os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`。
- **2 层 = tools/ 层** (多一层), 读 registry/模型路径全错 (如 models/saved/registry.json → tools/models/saved/).
- 全文件搜索 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 核对, 只有**确实指向 tools/ 内部**的才保留 2 层。
- 方法归属坑: `_refresh_deploy_models` 曾误定义在 InferencePanel 类内 (TrainingModule 调用 → AttributeError → 下拉空, 异常被 try 吞)。**新方法必须定义在调用者类内**; 定位类边界用 `grep -n '^class '` + 方法行号。

## 6. ECS 磁盘限制 (容器 tar 传不了的根因)
- ECS 40G 盘 (剩余 ~8G), 容器 tar (GB 级) 传不上去。**只传模型文件 (87MB)**; arm64 容器由 Mac 本地构建 (原生, 无需 qemu)。
- 4090 交叉构建 arm64 需要 buildx + qemu-user-static (exec format error 是没装 qemu); 即使装了, 大 tar 也传不过 ECS — 别走这条路。

## 7. 部署下拉 (VEH.2.27) 布局与填充
- 布局: 上传容器(29)最左 → 推送到Orin(28)中间 → 部署模型下拉(27)最右 (用户多次纠正顺序, 以此为准)。
- 下拉填充 `_refresh_deploy_models`: 读 registry.json, **ACT 优先在首** (`sort key (0 if pol=='act' else 1)`), itemData=pretrained_model 绝对路径。
- 模型源优先级: 下拉选中 → ckpt_edit → registry 最新 ACT。
