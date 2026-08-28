# 远程 4090 训练链全链路修复 (2026-08-09)

新 GPU: RTX 4090 24G @ 223.109.239.30:15032 (gpu_4090, SSH root, Ubuntu22 / CUDA 12.4 / Driver 550 / nvidia-container-toolkit 1.19.1 已装)。
SSH 凭据唯一权威来源 `~/.zmax_ssh.json` **嵌套结构** `{gpu_v100:{...}, gpu_4090:{...}}` — 加载端必须兼容嵌套+旧扁平, 保存端合并更新对应 key (不覆盖另一台)。

## 远程容器训练 5 连坑 (全部踩过, 按序排查)

1. **容器 conv 崩 `CUDNN_STATUS_NOT_INITIALIZED` (终极根因)**:
   - 症状: `torch.cuda.init()` OK + `torch.backends.cudnn.is_available()` True, 但首次 Conv2d 崩 CUDNN_STATUS_NOT_INITIALIZED; 训练在 "Creating policy" 后 22 秒 exit 1
   - 根因: 镜像 cuDNN 9.19 + 驱动 550.127 组合下 cuDNN 运行时初始化失败
   - 诊断链: ①`docker events` 抓 exitCode=1 + execDuration=22 ②前台 docker run 复现拿完整 traceback ③逐步隔离: cuda init OK → conv 崩 → `cudnn.enabled=False` 后 conv OK (输出 torch.Size([2,16,224,224]))
   - **修复 = 训练入口禁用 cuDNN** (`remote_train_entry.py`):
     ```python
     import torch
     torch.backends.cudnn.enabled = False
     import sys
     sys.argv = ['lerobot_train'] + sys.argv[1:]
     from lerobot.scripts.lerobot_train import main
     main()
     ```
   - **环境变量 `TORCH_CUDNN_ENABLED=0` 无效** (torch 不读), 必须代码级禁用
   - 训练命令统一 `python remote_train_entry.py --config_path xxx` (容器入口改这个, 3 处提交路径全要改: studio×2 + simulink)
   - 禁用后实测 1.1 step/s, 2000 步 ~33 分钟完成, loss 正常下降

2. **`docker run -d ... > /tmp/remote_train.log` 只重定向容器 ID**:
   - docker run -d 的 stdout = 容器 ID (一行 hex), 训练日志在容器内 → tail /tmp 文件只看到一行 ID
   - **日志必须 `docker logs zmax_train` 拉取** (增量 `tail -n +N` 或全量去重, 📡 前缀实时打印)
   - 容器退出后 `docker logs` 仍可查 (容器别加 --rm, 或退出后立即拉)
   - "容器已退出 — 日志流停止" 判定: `docker ps -q --filter name=zmax_train` 空

3. **output_dir FileExistsError (resume:False)**:
   - config 固定 output_dir (如 act_metaworld_final) 已存在 → lerobot 拒绝覆盖 → 训练秒崩
   - **修复: 提交前 sed 改 output_dir 为时间戳唯一目录**:
     ```bash
     sed -i "s|^output_dir: .*|output_dir: outputs/train/<cfg名>_$(date +%Y%m%d_%H%M%S)|" config_xxx.yaml
     ```
   - cfg 名带 config_ 前缀 (config_act_metaworld_<ts>); 拉回时 glob 要匹配这个前缀 (`ls -dt outputs/train/config_act_metaworld_*`)
   - f-string 嵌套引号坑: `{cfg.split('.')[0]}` 内引号冲突 → 用 `{cfg[:-5]}` 切片或预计算变量 `_odir = cfg_base.replace('.yaml','') + '_$(date...)'`

4. **远程 GPU 挂载方式**: 4090 装 nvidia-container-toolkit (`nvidia-ctk runtime configure --runtime=docker` + restart docker) → daemon.json 有 nvidia runtime → **`docker run --runtime nvidia --gpus all`**。不带 --runtime 会 "could not select device driver" / 找不到驱动。本地 WSL2 用 `--gpus all` 即可 (toolkit 原生), **远程 Linux 必须 --runtime nvidia --gpus all**; 别用 --device 透传 + 手挂 libcuda (cuDNN 反而崩)。

5. **远程 git pull 冲突**: 远程仓库常有未提交改动 (config root/reports) → pull abort。用 `git reset -q --hard origin/main` (远程是执行端, 本地改动都是运行时产物); fetch 要指定分支 `git fetch origin main`。

## Model Zoo 队列远程模式误判"完成"循环刷屏

- 症状 (老倪: "你都显示自动交付了"): `🏁 Model Zoo 完整训练完成` + `📤 自动交付` 每 15 秒重复出现
- 根因: 队列 `_zoo_next` 用 `pgrep lerobot_train` 判训练是否完成 — **远程容器训练时本地无此进程** → 每 15s 轮询判定"完成" → 无限触发自动交付 (生成视频/PDF/发飞书, 白烧资源)
- 修复双保险:
  1. `_zoo_finalized` 标志 — 完成分支只触发一次自动交付 (`if getattr(self, "_zoo_finalized", False): return`)
  2. `_zoo_remote_wait` — on_train 返回 "容器化远程提交" 时设该 policy, 轮询改查**远程 docker 容器** (`docker ps -q --filter name=zmax_train`), 在跑则等, 退出才推进队列
- 新一轮训练重置 `_zoo_finalized = False`

## 训练完自动拉回模型 (模型引擎可见路径)

- 容器退出 → `_pull_remote_model`:
  1. ssh 找远程最新输出目录 (glob `outputs/train/<cfg名>_*`)
  2. scp 远程 `checkpoints/last/pretrained_model` → 本地 `outputs/train/<name>_<ts>/checkpoints/last/pretrained_model`
  3. 写 `reports/train_curve_<policy>.json` 记录 ckpt (供 rollout/推理消费) — **ckpt 字段必须指向 `.../checkpoints` 目录** (rollout 的 load_policy 拼 `base/last/pretrained_model`, 不是 base 本身)
  4. 注册 `models/saved/registry.json` (模型引擎下拉)
  5. 回填 ckpt_edit
- **拉回目录 checkpoints 下只有 last/ 无数字目录 → DatasetModule 启动崩**: `max([int(b) for b in os.listdir(ck) if b.isdigit()])` 对空列表抛 ValueError → 控制台启动即崩。**修复: 空列表回退 0 + try/except**
- policy 映射: model_combo 名 → rollout 名 (ACT→act, SmolVLA→smolvla, SmolVLA+LEW→smolvla_lew, VLA-Touch→vla_touch, AWE→awe_zflow, MLP蒸馏→expert_mlp, 官方专家→expert_policy)

## 端侧部署 = 静态 URL 覆盖即部署 (小芳确认链路)

- 链路: `[4060 模型] → ECS 静态 URL → Mac 轮询拉取 → arm64 容器 → Orin` (老倪: "模型下载=推到MAC")
- 实现:
  1. scp `model.safetensors` → ECS `/www/wwwroot/datadrive.world/models/act_<ts>.safetensors` + `act_latest.safetensors` (覆盖即部署)
  2. **chmod 644 铁律**: scp 保留 600 权限 → nginx www 用户读不了 → 403。上传后立即 `chmod 644` 两个文件
  3. 验证 `https://datadrive.world/models/act_latest.safetensors` HEAD 200 + 断点续传 206 (nginx `location ^~ /models/` 静态服务已配, Cache-Control no-cache)
  4. `POST /api/relay/command` 下发 Mac 部署指令 (`git clone 仓库 && docker build --target infer && curl 拉模型 && echo READY`) — Mac 守护轮询 command.json 执行
- **Mac arm64 原生构建 >> 4090 交叉编译**: 4090 无 buildx (`apt install docker-buildx` 0.20.1), arm64 交叉构建需 qemu (`apt install qemu-user-static binfmt-support` + `docker run --rm --privileged multiarch/qemu-user-static --reset -p yes`), exec format error = 无 qemu。**Mac 原生 arm64 `docker build --target infer` 最快最稳** (小芳 Mac: Docker 24.0.5, arm64, 118G)
- Orin Docker 权限坑: 装了但用户不在 docker 组 → `sudo usermod -aG docker tashan && newgrp docker`
- GUI: VEH.2.31「📥 推送到 Orin」按钮 + 模型下拉 (ACT 优先在首 = 默认第一个), **端侧部署模式高亮选中才可点** (其他模式禁用, 初始禁用)

## 仿真渲染无头化 (容器内 rollout 出视频, 2026-08-09)

- 症状: 容器内跑 rollout_video.py, 模型加载成功 (resnet18 下载完) 但渲染崩 `GLFWError: X11: Failed to open display :0` (glfw 需 X11) 或 `AttributeError: 'NoneType' object has no attribute 'eglQueryString'` (egl 库坏)
- 根因: 容器无显示环境 + 无渲染依赖 (libglfw3/libegl1/xvfb)
- **修复三件套**:
  1. **容器装依赖**: `apt-get install -y libglfw3 libegl1 xvfb` (Debian 13 trixie 包名如此; libegl1-mesa 不存在)
  2. **docker commit 固化为新镜像**: `docker run --name zmax_render_fix --entrypoint bash zmax-std:1.0 -c "apt-get update && apt-get install -y -qq libglfw3 libegl1 xvfb && which Xvfb"` → `docker commit zmax_render_fix zmax-std:render` → `docker rm -f zmax_render_fix`。**commit 前必须确认容器内 `which Xvfb xvfb-run` 都输出** (apt 装完才 commit; 提前 commit = 依赖缺失白做)
  3. **跑 rollout 用 xvfb-run**: `docker run --rm --gpus all -v $PWD:/app ... --entrypoint bash zmax-std:render -c "xvfb-run -a -s '-screen 0 1280x1024x24' python /app/tools/rollout_video.py ..."`
- **MUJOCO_GL 默认改 egl** (rollout_video.py 顶部, import mujoco 前): glfw 需 X11 (容器无 → 崩), egl 无头 GPU 渲染。但 egl 在缺 libEGL 系统库时 `eglQueryString None` — 装了 libegl1 后正常
- 验证: rollout 日志尾 `✅ rollout 完成: ... 60帧 · 14.92fps · 动作均值 1.0165` = 渲染真成功
- **帧→mp4 合成**: `ffmpeg -y -framerate 20 -i frame_%04d.png -c:v libx264 -pix_fmt yuv420p out.mp4`; 对比视频 hstack 双拼前**两视频帧率/时长必须统一** (`fps=20` + `tpad=stop_mode=clone`), 否则 xstack 报 `Failed to configure output pad` (本会话 ffmpeg 版 xstack 不稳, 用 hstack 替代)

## 部署链路详细反馈 (老倪: "ECS的信息也要打印出来, 要不我怎么知道是否连接成功")

- **铁律 (2026-08-09 老倪明确)**: 端侧部署/上传类操作必须逐步打印反馈, 不能"📤 上传…"后静默 2 分钟。scp 87MB 无进度 = 用户报"没反应/到底部署成功没有"
- **完整反馈链**:
  1. `GET https://datadrive.world/api/relay/status` → 打印 `📡 ECS 中转在线: relay vX · 队列 N 包`
  2. SSH 探测 → `🔌 ECS SSH 连通: OK`
  3. **分块上传替代 scp** (8MB 块, ssh `cat >>` 追加, 每 5% 打印 `└ name: N% (xxKB/yyKB) · zzzKB/s` + 完成 ✅ + 耗时) — scp 单进程 87MB 要 2 分钟零反馈; 分块有实时百分比。**上传前先 `rm -f` 远程同名文件** (防 cat >> 追加残留)
  4. chmod 644 → `🔓 chmod 644 完成`
  5. `HEAD https://datadrive.world/models/act_latest.safetensors` → `✅ 静态 URL: HTTP 200 · NNNKB`
  6. `POST /api/relay/command` → `📡 已下发 Mac 部署指令`
  7. `GET /api/relay/orin/status` → `🤖 Orin: 在线/离线 · 模型 X · 推理 N次`
- **ECS 上传后必查权限**: scp/分块保留本地 600 → nginx www 读不了 → HEAD 200 但实际下载 403。**每批上传后 `chmod 644` 并 `ls -la` 验证** (14:42 上传的 600 权限文件就是漏 chmod, 小芳 HEAD 200 但文件实际不可读)
- **模型文件可能多份 (版本化 act_<ts> + act_latest)**: 用户多次点击会产生多个版本文件, 哈希可能不同 (不同模型源) — act_latest 指向最新即可, 旧版本不影响。验证 act_latest 正确性: 对比本地源 sha256

## 仓库根路径 (tools/gui/studio.py 内)

- `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` = **tools/** (多一层!) — studio.py 在 tools/gui/ 下, 仓库根需要 **3 层 dirname**
- 2 层 dirname 读 registry.json → `tools/models/saved/registry.json` 不存在 → 下拉空 / 部署找不到模型
- 正确: `os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`
- **方法定义放错类**: `_refresh_deploy_models` 原写在 InferencePanel (有 `_saved_registry_path`), 但 TrainingModule 调用 → AttributeError 被 except 吞 → 下拉空。方法属主必须与调用方同类 (TrainingModule 内实现, 直接用 3 层 dirname 拼 registry 路径, 不依赖 InferencePanel 方法)

## GUI 点击无反应排查 (SimCanvas._items AttributeError)

- 症状: 日志区刷屏 `AttributeError: 'SimCanvas' object has no attribute '_items'` (mouseReleaseEvent 每次点击触发), 用户感觉"点击没反应"
- 根因: `self._items` 定义在 **SimulinkModule** (2568行), 但 **SimCanvas** (2170行, 独立类) 的 mouseReleaseEvent 引用 `self._items` → AttributeError。SimCanvas 有 `self.module` 引用
- 修复: `it = self.module._items.get(nid) if self.module else None`
- **教训: 画布/视图类访问节点表必须经 module 引用, 别假设视图自己持有**; 日志区反复刷同一条 AttributeError = 有控件事件处理器引用了错误属主, 先 grep 该属性在哪些类定义/引用

## GUI 部署行布局 (老倪 2026-08-09 三轮调整)

- 最终: **推送到 Orin (28) 整行最左** → 部署模型 label+下拉 (27) → 上传容器 (29) → stretch
- 上传容器按钮并入部署行 (删除原独立 rowc), 不再单独一行
- VEH.2.xx 编号 = `_veh2_apply` 按布局位置 (y 优先上→下, 再 x 左→右) 运行时自动编号, 源码注释里的编号只是构建时近似 — 用户报 "VEH.2.28 放最左" 时先确认该编号对应哪个控件 (悬停 tooltip 显示 ID+控件名)

