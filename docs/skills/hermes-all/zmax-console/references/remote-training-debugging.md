# 远程 GPU 训练调试链 (2026-08-09 会话沉淀)

远程训练 = 控制台 SSH 提交 → 远程 4090 (223.109.239.30:15032) docker 容器 → 训练完拉回模型。
本文件记录完整调试链, 均为实测根因与修复, 别再重复踩。

## 1. cuDNN CUDNN_STATUS_NOT_INITIALIZED — 远程训练崩溃头号根因
- 现象: torch.cuda.is_available()=True, torch.backends.cudnn.is_available()=True, 但**任何 conv2d 调用** → `RuntimeError: cuDNN error: CUDNN_STATUS_NOT_INITIALIZED`, 训练启动 22s 内 exit 1。
- 环境: zmax-train:latest 镜像 (torch 2.4.1+cu124, cuDNN 9.19) + 主机驱动 550.127 (CUDA 12.4)。
- 无效尝试: `-e TORCH_CUDNN_ENABLED=0` 环境变量 **torch 不读**, 无效。
- 修复: 启动前 `torch.backends.cudnn.enabled = False` → 训练正常 (略慢, 可接受)。落地为仓库根 `remote_train_entry.py`:
  ```python
  import torch
  torch.backends.cudnn.enabled = False
  import sys
  sys.argv = ['lerobot_train'] + sys.argv[1:]
  from lerobot.scripts.lerobot_train import main
  main()
  ```
- docker 启动**必须** `--runtime nvidia --gpus all` (该 docker 版本单独 `--gpus all` 报 "Found no NVIDIA driver"); 已验证 nvidia-container-toolkit 1.19.1 就绪 (daemon.json 有 nvidia runtime)。
- 快速验证 conv 是否正常:
  ```
  docker run --rm --runtime nvidia --gpus all --entrypoint python zmax-train:latest -c \
  "import torch,torch.nn as nn; torch.backends.cudnn.enabled=False; \
  x=torch.randn(1,3,224,224,device='cuda'); y=nn.Conv2d(3,16,3,padding=1).cuda()(x); torch.cuda.synchronize(); print('CONV_OK')"
  ```

## 2. docker run -d 重定向陷阱 — 日志流只显示容器 ID 的根因
- `docker run -d ... > /tmp/remote_train.log 2>&1` 重定向的是 **docker run 命令本身输出 = 容器 ID**, 不是容器内训练日志!
- 容器内日志必须 `docker logs zmax_train 2>&1 | tail -n +N` 增量拉取 (N = 已读行数)。
- `--rm` + 每次提交 `docker rm -f` 会删容器日志 → 崩溃原因诊断不到。诊断期去掉 --rm 或先抓 logs 再删。

## 3. lerobot output_dir FileExistsError — 训练启动即崩第二根因
- config `output_dir` 固定 (如 outputs/train/act_metaworld_final) + `resume: False` + 目录已存在 → lerobot 拒绝 → exit 1。
- 修复: 提交命令里 sed output_dir 为时间戳唯一目录:
  `sed -i "s|^output_dir: .*|output_dir: outputs/train/<cfg名>_$(date +%Y%m%d_%H%M%S)|" <cfg>`
- f-string 里 cfg 名去 .yaml 用 `{cfg[:-5]}` 切片 (无引号, 安全); 不要 `{cfg.replace(".yaml","")}` (嵌套引号 f-string 语法错)。

## 4. Model Zoo 队列远程误判 — "训练完成"循环刷屏 + 重复自动交付
- 根因: 远程容器训练时**本地无 lerobot_train 进程** → `_zoo_next` 的 `pgrep -f lerobot_train` 判"训练完成" → 15s QTimer 轮询无限触发 "🏁 Model Zoo 完整训练完成" + 重复调 `_auto_finalize()` (生成视频/PDF/发飞书, 白烧资源)。
- 修复 (studio.py `_zoo_next`):
  - `_zoo_finalized` 标志: 完成分支只触发一次自动交付, 已交付直接 return。
  - `_zoo_remote_wait`: on_train 返回含 "容器化远程提交" → 设 `_zoo_remote_wait=pol`, 轮询时 SSH `docker ps -q --filter name=zmax_train` 容器还在则等, 退出才推进队列。
  - 新一轮训练重置 `_zoo_finalized = False`。

## 5. 远程模型拉回链 (训练完 → 模型引擎可见路径 → Simulink 推理消费)
- 触发点: 日志流 `_poll_remote_log` 检测容器退出 → `_pull_remote_model()`。
- 流程 (studio.py `_pull_remote_model`):
  1. 远程 glob 最新输出目录: `ls -dt ~/lerobot-smolvla-lew/outputs/train/{cfg_full}_*` — **注意 cfg_full 带 config_ 前缀** (output_dir sed 用完整 cfg 名)。
  2. 找 checkpoint: `ls -d <dir>/checkpoints/*/pretrained_model | sort | tail -1` (最后 = last)。
  3. scp -r 到本地 `outputs/train/<name>_<ts>/checkpoints/last/pretrained_model` (name = cfg 去 config_ 去 .yaml)。
  4. 写 `reports/train_curve_<policy>.json` (ckpt 字段指向本地目录) — **Simulink rollout 按 train_curve_<policy>.json 找模型**。
  5. 注册 `models/saved/registry.json` (模型引擎下拉) + 回填 `ckpt_edit.setText` (模型引擎「模型:」路径可编辑)。
- policy 名 ≠ cfg 名: cfg=config_act_metaworld.yaml → name=act_metaworld, policy=act (rollout 按 policy 读 train_curve_act.json)。
- 拉回目录只有 last/ 无数字 checkpoint → 必须给 DatasetModule 空列表保护 (见下)。

## 6. DatasetModule 启动崩溃 — max([]) 空列表
- 拉回目录 checkpoints/ 下只有 last/ (无纯数字目录) → `max([int(b) for b in os.listdir(ck) if b.isdigit()])` → ValueError, 控制台启动即崩。
- 修复: try/except + `steps = max(_nums) if _nums else 0`。

## 7. PyQt5 子线程日志丢失 (通用坑, 已在 ssh-remote-gpu ref 记录, 复述关键)
- `QTimer.singleShot(0, ...)` 与 `QMetaObject.invokeMethod` 从子线程调 _append_log **都会丢消息** (offscreen 可复现: 线程逻辑跑完但日志一条不显示)。
- 可靠方案: 非主线程 → `self._log_queue.append(text)`; 主线程 QTimer 200ms → `_flush_log_queue` 逐条 append。日志队列 + flush 定时器在 TrainingModule.__init__ 初始化。

## 8. QTextEdit 光标/行高两倍
- log_text `padding: 8px` 上下留白 → 行距/光标视觉两倍 → 改 `padding: 2px 4px`。
- WSLg 下 Consolas 回退字体行高异常 → 显式 `QFont("Consolas",11)` + `setStyleHint(QFont.Monospace)` + `document().setDocumentMargin(0)`。

## 9. 看护脚本模式 (长训练保证成功)
- 用户要求"盯着, 断了自动重启": 后台 python 脚本 60s 轮询远程 `docker ps` + 日志步数;
  容器退出→自动诊断(查 docker logs 尾)→自动重跑; 步数停滞 N 轮→强制重启; 2000/2000→退出。
- 跑法: `terminal(background=True, notify_on_complete=True)` 起 `/tmp/watch_remote_train.py`。

## 10. f-string→shell→awk 三层转义铁律 (多次踩坑)
- 文件源码 `\\$3` (2 反斜杠) → f-string 渲染 `\$3` → shell 双引号内 → awk 收到 `$3` ✓
- 文件源码 `\\\\$3` (4 反斜杠) → awk 收到 `\\$3` → `awk: unexpected character '\'` ✗
- **验证法**: 对该行 `eval()` 看渲染结果, 不要看 repr (终端双重转义误导); 再真实执行整条 ssh 命令。
- 复杂转义行用 patch 会再踩坑 → 用 execute_code 按行索引重建 (chr(92) 拼反斜杠) 或直接避免 awk: 远程命令输出整行 `df -h / | tail -1`, Python splitlines 解析。
- simulink_module.py 与 studio.py 各有独立提交路径, **两处都要改** (grep 'docker run' 找全)。

## 11. 容器无头渲染 (mujoco/glfw) — rollout 视频生成三坑
- 现象: 容器里跑 rollout_video.py, 模型加载成功 (下载 resnet18) 后崩: `GLFWError: X11: Failed to open display :0` 或 `AttributeError: eglQueryString None` (PyOpenGL EGL 绑定, 容器缺 libegl 系统库)。
- 根因: `MUJOCO_GL=glfw` 需要 X11 显示; 容器无 DISPLAY。WSLg 挂载 `/mnt/wslg` + `/tmp/.X11-unix` 依赖会话存活, 不可靠。
- 修复 (一次到位, 无头 GPU 渲染): 容器 apt 装 `libglfw3 libegl1 xvfb` → `docker commit` 固化为 `zmax-std:render` → 跑 rollout 用:
  ```bash
  docker run --rm --gpus all -v $PWD:/app -w /app -e PYTHONPATH=/app/src \
    --entrypoint bash zmax-std:render -c \
    "xvfb-run -a -s '-screen 0 1280x1024x24' python /app/tools/rollout_video.py --policy act ..."
  ```
- 坑①: **docker commit 时机要在 apt 真正完成后** (曾 commit 太早 → 镜像里 0 个依赖, `which Xvfb` 空)。apt 装完要确认 `which Xvfb xvfb-run` 再 commit; 用 background+notify 跑完整 apt+commit 链。
- 坑②: Debian 13 (trixie) 包名是 `libegl1` (无 `libegl1-mesa`); 源要 `apt-get update` 先跑 (新容器源未更新 apt-cache 为空)。
- 坑③: 容器默认 `MUJOCO_GL=glfw` → 顺手把 rollout_video.py 默认改 `egl` (setdefault), 但 egl 在缺 libegl 的旧镜像仍坏 → 以 render 镜像 + xvfb-run 为最终方案。

## 12. rollout ckpt 结构不匹配 — "checkpoint 不存在" 的隐形原因
- rollout_video.py 的 `load_policy`: `base_dir = ROOT/ckpt_base` → 拼 `base_dir/last/pretrained_model` (无 checkpoints 层)。
- 而 lerobot 训练产物是 `outputs/train/<name>_<ts>/checkpoints/last/pretrained_model`。
- 所以 **train_curve_<policy>.json 的 ckpt 字段必须指向 `<name>_<ts>/checkpoints` (含 checkpoints 层)**, 不是 `<name>_<ts>`。写错 → 容器里 `os.path.isdir(base/last)` False → `FileNotFoundError: checkpoint 不存在` (但目录明明存在, 极易误判为挂载问题)。
- 拉回代码 `_pull_remote_model` 写 curve 时用 `os.path.join("outputs","train",name_ts,"checkpoints")`。验证法: 容器内跑 `os.path.isdir(base+'/last/pretrained_model')`。

## 13. 飞书发文件 (mp4/media + Content-Length) — 400 与 230055
- 飞书上传 `POST /im/v1/files` (multipart) 后发消息, 两个必踩坑:
  - **mp4 必须用 `msg_type: "media"` (视频消息)**, 用 "file" → 230055 "The type of file upload does not match the type of message being sent"。pdf 等其他类型用 "file"。
  - **multipart 与 JSON post 都要显式 `Content-Length` 头**, 否则 urllib 发 → HTTP 400 (python3.14 urllib 不自动算)。加 `"Content-Length": str(len(body))` 即通。
- 上传成功标志 `r2["data"]["file_key"]`; 消息发送 `POST /im/v1/messages?receive_id_type=chat_id` with `{"receive_id": chat_id, "msg_type": msg_type, "content": json.dumps({"file_key": fkey})}`。
- 完整可复用脚本: zmax-console `templates/send_feishu.py` (上传→media/file 消息→文本说明)。

## 14. ffmpeg 对比视频拼接 (xstack/hstack)
- 两个输入视频帧率不同 (20 vs 12) / 时长不同 → xstack 报 `Failed to configure output pad`。先各自 `scale + fps=N + format=yuv420p` 统一, 或 `tpad=stop_mode=clone` 补时长。
- 本机 ffmpeg xstack 编译缺失时用 **hstack 等价** (水平拼接, layout=0_0|w_0_0 同 xstack 双输入)。
- 输出文件名含空格 (`Model Zoo_rollout_*.mp4`) → `ls` 通配要引号或用 grep 过滤, 别裸通配。
