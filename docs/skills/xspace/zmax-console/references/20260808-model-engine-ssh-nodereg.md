# 20260808 模型引擎 + SSH + 新节点注册 + Windows 修复

## 1. 模型引擎 (Model Engine) — 训练控制台改名 (2026-08-08 老倪)
- 首页卡/导航/页标题全部改名: 训练控制台 → 模型引擎 (Model Engine)
- **SmolVLA 是 7 模型下拉之一** (老倪: "你的SmolVLA变成其中一个列表之一的选择"):
  - `QComboBox`: [ACT, SmolVLA, SmolVLA+LEW, VLA-Touch, AWE, MLP 蒸馏, 官方专家]
  - `currentTextChanged → _on_model_changed(name)`: param_group 标题跟随 + model_name 属性摘要
  - 摘要探测: `glob outputs/train/*<tag>*` 最新目录 → `<目录名> · <步数> 步 · <时间>`
  - tag 映射: {"MLP 蒸馏":"expert_mlp","官方专家":"expert_policy","ACT":"act","SmolVLA":"smolvla","SmolVLA+LEW":"smolvla_lew","VLA-Touch":"vla_touch","AWE":"awe_zflow"}
  - 🐛 摘要读取必须 `os.path.isdir(checkpoints)` 守卫 (expert_mlp 是 .pt 非目录 → listdir 抛错被吞 → 显示空)

## 2. SSH GPU 服务器面板 (老倪: "模型引擎可以连接GPU服务器")
- 默认预填: `ssh root@223.109.239.36 -p 24212` — 用户可编辑, 留密码输入框
- 输入框: host / **port** / user / password(掩码) + 🔌 连接按钮 + 状态标签
- 凭据存 `~/.zmax_ssh.json` (host/port/user/pwd) — 启动时载入覆盖默认
- 连接逻辑 `_connect_gpu`: **必须 threading.Thread 后台** (防卡 UI), 完成后 `_set_ssh_status`
  ```python
  cmd = f"sshpass -p '{pwd}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 -o Port={port} {user}@{host} \"nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader | head -1; echo '---'; ps aux | grep -c '[l]erobot_train'; echo '---'; df -h / | tail -1 | awk '{print $3, $5}'\""
  ```
  ⚠️ **sshpass+ssh 端口坑 (实测)**: `-p 24212` 会被吞 → ssh 连 **port 22** (Connection refused, -v 可见 `Connecting to ... port 22`) — **必须 `-o Port={port}`** 形式
- 状态显示: `✅ host · GPU ... · 训练进程 N · 磁盘 ...`

## 3. Simulink 新节点类型注册清单 (KeyError: 'coord_overlay' 教训)
新节点类型 (如 coord_overlay) 必须 **5 处全注册**，漏一处就崩:
1. `NODE_TYPES` 字典 (cn/color) — simulink_module.py ~36 行
2. `add_node` 的 **icon 字典** (KeyError 来源!) — ~3119 行: `"coord_overlay": "🧩"`
3. `COLORS[ntype]`
4. `node_logic.py` `_reg(ntype, [关键词...], desc, fn)` — 关键词含新名 (几何条件)
5. LIBRARY 条目 (模块库可拖)

## 4. 模板 node_specs 索引陷阱 (⚠️ 严重)
- 模板加载按 **node_specs 顺序索引** 匹配 edges (`(0,1),(1,3)...`)
- 把共享节点定义**插在 node_specs 中间** → 后续所有节点索引错位 → edges 全乱
- **新定义放 node_specs 末尾** (布局用名字定位, 不依赖索引)
- 同名多定义 = 多实例 (布局同名多行 → 各占一个位置, used 去重)
- 5 个 🧩 → 1 个共享 (老倪: "连接了好几个,好乱,简化") → 布局删各模型行, 只留感知链 1 处

## 5. 几何条件 (Geometric Conditioning) — 坐标叠加改名
- 老倪命名: 坐标叠加 → **几何条件** (本质 = 目标结构坐标加性投影注入 latent, 图像作背景 token 旁路; **不是调制/不是控制模态** = 加约束 boundary condition)
- add_node 特判端口 (老倪: "输入输出奇怪"):
  ```python
  if ntype == "coord_overlay":
      inputs  = [{"id":"in1","label":"bbox","dtype":"geo"}, {"id":"in2","label":"latent","dtype":"latent"}]
      outputs = [{"id":"out1","label":"latent+","dtype":"latent"}]
  ```
- 🐛 **多端口渲染坑 (老倪两次: "几何条件没有输入输出")**: SimNodeItem.paint 的端口绘制**按连线数** (无连线 → 中间一个点, 无标签) — 端口数据在 node["inputs"] 但没画!
  - **修复**: paint else 分支开头加 `if len(ins) > 1 or len(outs) > 1:` → 按定义逐端口画圆点 (py = h*(i+1)/(n+1)) + 标签文字 (bbox/latent 左侧, latent+ 右侧) → return
  - **加高节点**: add_node 特判 `"h": 84 if ntype == "coord_overlay" else 50` (DH=50, 默认必须保持 50 否则全布局移位)
  - 验证: offscreen 加载模板 → 节点 inputs/outputs label 数组断言 (数据在 ≠ 渲染在, 两处都要查)

## 6. Windows exe 启动崩溃修复 (v1.7.2)
- 根因: PyInstaller onefile 的 cwd = `C:\Users\<u>\AppData\Local` — `_local_datasets` 裸 `os.listdir(root/data)` → FileNotFoundError
- **所有文件系统探测必须 isdir 守卫** (Windows 无 data/ → 跳过返回空列表, 不抛)
- 验证: `_repo_root = lambda: "/tmp/nonexistent"` 模拟 Windows → 空列表不炸

## 7. GUI 多实例 + auto_restart 守护 (10:33 事件)
- 飞书端 gateway (hermes gateway run) 会拉起 `bash -lic "set +m; cd ... && python3 studio.py > /tmp/studio_restart*.log"` 守护 — **kill studio 后自动再拉起** (像"崩了又开")
- **pkill -f 'studio.py' 会匹配自身命令行 → 自杀 exit -9** — 用精确 `ps -o pid,ppid,cmd` 找 PID 再 kill -9
- 多个 studio 实例并存 (183019+183197): 全部清理后再启一个干净的

## 9. Model Engine 封装完成版 — GPU 引擎选择 + 统一训练模式 (老倪: "所有训练都要用 model engine, 负责GPU服务器选择本地/远程")
- **引擎选择 radio**: `radio_local`(本地 RTX 4060, 默认勾选) + `radio_remote`(远程, 连接前禁用)
  - **布局: radio 必须在页面最顶部** (老倪: "上面要显示要用户选择本地/远程; 远程有连接ssh按钮") — engine_box 在 SSH 面板之前 addWidget; SSH 面板存 `self.ssh_box` 引用
  - `_set_engine_ui(True, gpu)`: 连接成功 → radio_remote 激活 + 文案 `远程 GPU (V100 · host)` + **默认 setChecked(True) 自动切远程**; 断开 → 恢复本地
  - `_on_gpu_mode`: radio_remote.isChecked() and remote_engine → `self.gpu_mode="remote"` else "local"
- **所有训练统一走引擎**:
  - TrainingModule._start_training 开头: `if gpu_mode=="remote" and remote_engine: _start_remote_training(); return`
  - **Simulink 训练节点接入**: StudioMainWindow 创建时 `self.model_engine = TrainingModule()` + `self.simulink.set_model_engine(self.model_engine)`; simulink_module `set_model_engine(engine)` 存 `_model_engine`
  - on_train 里 config 映射后、本地启动前: `if me and me.gpu_mode=="remote" and me.remote_engine:` → SSH 提交远程 (git pull 同步 + `sed -i "s|^  root: .*|  root: data/metaworld_peg|"` 改远程数据路径 + nohup 启动) → return; 失败回退本地
  - 🐛 **提交命令必须 `python3` 非 `python`** — 服务器只有 python3 (无 python 别名); `nohup python ...` 秒失败 (`nohup: failed to run command 'python'`) 但 ssh `& echo $!` 仍返回 pid → 日志假阳性"远程训练已启动"
  - 🐛🐛 **lerobot 是 pip 包不是仓库目录** — `lerobot/scripts/lerobot_train.py` 在 site-packages (本地 lerobot/ 目录不存在! 本地也是 pip 装) → 远程提交必须**模块方式**: `nohup /root/lerobot-venv/bin/python3 -m lerobot.scripts.lerobot_train --config-path <cfg> > /tmp/remote_train.log 2>&1 & echo $!` — 路径方式会 `can't open file ... No such file` 秒崩
  - 🐛 **提交后必须验证进程存活且防假阳性**: sleep 3 后 ssh `ps -eo pid,cmd | grep "[l]erobot_train" | grep -v ssh` + `tail -2 /tmp/remote_train.log` → alive = 有进程行 AND 日志无 Error/Traceback/"No such file" — **必须排除 ssh 自身** (旧 grep -c 会匹配提交 shell → 假"存活")
- **连接外部资源自动 clone** (_connect_gpu 成功分支): `ls -d lerobot-smolvla-lew || git clone --depth 1 https://github.com/MikeBMW/lerobot-smolvla-lew.git` — 统一训练代码
- **远程进度轮询**: `_start_remote_progress_poll(cfg)` QTimer 30s → `_poll_remote_progress` ssh 查 `outputs/train/<name>/checkpoints` 最大步数 → `_update_progress(pct)` + 日志; 进程消失 → 完成停 timer
- config 映射: ACT→config_act_pegdata.yaml, SmolVLA→config_smolvla_peg_long2.yaml, 其余 *_ft.yaml

## 10. 远程 GPU 服务器部署 (223.109.239.36 — Tesla V100-SXM2-32GB, ubuntu22)
- ⚠️ **2026-08-08 服务器重启后 SSH 端口/密码变更**: 24212/neeh3Yah → **24424/da9eo7yo** (老倪 mid-turn 给新凭据; 服务器 up 2min 恢复后新端口生效 — 连接被拒先怀疑端口/密码变了, 查 memory)
- **已迁移容器化 (Docker 优先, 本页 venv 方案为过渡期记录)**: 训练环境 = `zmax-train` 镜像 (Dockerfile: pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime + `pip install -e .`) → `docker run --gpus all` 提交, 见第 13 节
- **python3.10 无 pip** (ensurepip 也没有) → `apt-get install -y python3-pip` (pip 22.0.2)
- 🐛 **lerobot 要求 Python >=3.12** — 服务器 3.10.12 `pip install -e .` → `ERROR: Package 'lerobot' requires a different Python: 3.10.12 not in '>=3.12'` (transformers 也没装上, 整轮依赖失败)
  - **方案**: `add-apt-repository -y ppa:deadsnakes/ppa` → `apt-get install -y python3.12 python3.12-venv` → `python3.12 -m venv /root/lerobot-venv`
  - venv 内装: `torch==2.2.2 torchvision==0.17.2 --index-url .../cu118` (**torch 2.1.2 不支持 py3.12** — 用 2.2.2; V100 sm_70 cu118 兼容) + `pip install -e .` (lerobot ✓)
  - 远程训练命令用 `/root/lerobot-venv/bin/python3` (或 venv activate)
- 依赖: `python3 -m pip install torch==2.1.2 torchvision==0.16.2 --index-url https://download.pytorch.org/whl/cu118` (V100 sm_70 支持 cu118) + `pip install -e .`
- 数据: `sshpass scp -r data/metaworld_peg root@host:~/lerobot-smolvla-lew/data/` (159M)
  - 🐛 **scp 目标目录必须已存在** — 远程 data/ 不存在时 `scp: failed to upload directory` → 先 `ssh mkdir -p ~/repo/data` 再 scp
- 依赖安装后台: `ssh "cd ~/repo && (pip install ...; echo DEPLOY_DONE) > /tmp/install.log 2>&1 &"` + 轮询 tail
  - 🐛 **INSTALL_DONE 不代表成功** — pip 缺失时整轮静默失败仍打 INSTALL_DONE → 必须 `python3 -c 'import torch'` 实验 + `pip --version` 先确认 pip 存在 (服务器 python3.10 无 pip → `apt-get install python3-pip`)
- 服务器无仓库: 自动 git clone (第 9 节); 训练命令用仓库内 config (git 里 root 是相对路径 data/xxx — 远程 sed 改 root)

## 11. Qt QSS 8位hex 颜色 = #AARRGGBB (alpha 在前!) + 远程环境状态轮询
- 🐛 **Qt QSS 8位 hex 是 `#AARRGGBB` (alpha 在开头)** — `#00d4aa88` 被解析为 **alpha=0x00 全透明** → 边框不可见!
  - 本会话: 四层分组框边框 `border:2px solid {gcol}88` — 架构层青色 `#00d4aa` 首字节 00 → **默认看不到边框, hover 才显示** (hover 用全色); 其他层"有边框"其实颜色也错乱
  - **修法: 边框一律用全色 `#RRGGBB` 或 `rgba(r,g,b,0.4)` 函数** (rgba() 明确不歧义); 标题/色条用全色, 边框暗淡用 rgba 40% — hover 再变全色
- **远程环境状态轮询** (老倪: "终端得显示远程环境是否还在安装"):
  - `self.remote_env_lbl` (SSH 面板行内最右) + `_start_env_poll()` (连接成功后启动 QTimer 30s) + `_poll_remote_env()`
  - 轮询: `ls /root/lerobot-venv/bin/python3 && venv-python -c "import lerobot; print(LEROBOT_OK)"` + `tail -1 /tmp/venv_install.log`
  - 状态: `🔧 远程环境: 安装中 · <日志尾>` (橙) → `✅ 就绪 (Python 3.12 + torch + lerobot)` (绿, 停 timer)

## 12. 远程 GPU 训练全链路检查表 (部署顺序)
1. 服务器: `git --version` / `python3 --version` / `nvidia-smi` / `df` — 无 pip 先 `apt-get install python3-pip`
2. **容器化 (2026-08-08 最终方案)**: 装 docker.io + nvidia-container-toolkit + Dockerfile + 镜像 `zmax-train:latest` (详见第 13 节) — venv 手动装是过渡方案
3. 远程仓库: 连接成功自动 clone (或手动 `git clone --depth 1`); 数据 `mkdir -p data && scp -r`
4. 提交训练: **`docker run -d --rm --gpus all -v ~/repo:/app -w /app zmax-train:latest python -m lerobot.scripts.lerobot_train`** + 提交后验证 (`docker ps --filter name=zmax_train` + 日志无 Error)
5. 每次改完代码: 本地 commit+push → 远程提交命令自动 `git pull` 同步

## 8b. 验证脚本断言坑 (本轮 5 次误报)- `QGroupBox.title()` 有前导空格 (setTitle(f" {name} ")) → 用 `"X" in title` 非 startswith
- `QComboBox.setCurrentText(当前值)` **不触发信号** → 先切到别的值再切回来/直接调方法
- `ModuleCard` 无 .title/.sys_label 属性 → 查 findChildren(QLabel) 的 badge 文本
- `_modules_grid()` 返回 **container QWidget** 不是 QGridLayout → `container.layout().itemAtPosition(r,c)`
- `cls.__new__(cls)` 免构造 → 信号未初始化 RuntimeError → 必须真实构造或 monkeypatch

## 13. 模型引擎容器化 (2026-08-08 最终方案 — 老倪: "专业的模型引擎, 应用容器化技术")
### 13.1 训练镜像 (Dockerfile + .dockerignore)
- 仓库根 `Dockerfile`: `FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime` + `COPY . /app` + `RUN pip install --no-cache-dir -e .` (V100 sm_70 兼容 cu12.1; torch 免重下 — 容器化核心优势)
- `.dockerignore`: data/ outputs/ reports/ *.mp4 *.pdf *.pt .git/ (159M 数据集不进镜像)
- **Dockerfile 必须 push 到 git** — 远程 clone 才有; 没 push 报 `unable to evaluate symlinks in Dockerfile path: lstat ... no such file`

### 13.2 服务器装 Docker (国内网络坑)
- `apt-get install docker.io` + nvidia-container-toolkit (GPU 直通) + `nvidia-ctk runtime configure --runtime=docker` + restart docker
- 🐛 **Docker Hub 拉取失败** (`failed to copy: httpReadSeeker ... registry-1.docker.io`) — 国内服务器必须配镜像加速: `/etc/docker/daemon.json` → `{"registry-mirrors": ["https://docker.1ms.run","https://docker.m.daocloud.io","https://dockerproxy.com"]}` + `systemctl restart docker`
- 🐛 **docker build 反复中断** (Pull fs layer 卡死) — 本地后台跑 ssh 前台 build (`ssh "cd repo && docker build ... > /tmp/docker_build.log 2>&1 && echo BUILD_DONE"` + notify_on_complete) — ssh 保持连接 build 不中断; 基础层缓存后重跑秒续
- 🐛🐛 **docker restart 会杀掉正在跑的 docker build** (buildkit 进程归 0, log 停在 Pull) — 本会话 CTK 安装里的 `systemctl restart docker` 直接中断了并行 build → **build 与任何 docker restart 严格串行**; 判断 build 卡死先 `ps aux | grep '[b]uildkit'` (0 = 被杀了, 不是慢)
- 🐛 **镜像状态判定坑**: `docker images -q zmax-train:latest` 有输出 ≠ 镜像可用 (构建中间态/daemon 重启) — 用 `docker run --rm zmax-train:latest python -c 'import torch, lerobot'` 实测; `docker images --format` 看完整列表

### 13.2b nvidia-container-toolkit 装不上 (国内服务器, 2026-08-08 实测全部失败) → 手动 GPU 透传
toolkit 目的 = 让 `docker run --gpus all` 自动注入 GPU — 国内服务器三条路全挂:
1. 🐛 **服务器没有 curl** (`curl: command not found`) — nvidia.github.io 官方源脚本、GitHub API 全用 curl → 全部静默失败 (nvidia-ctk not found 的根因) — **一律用 wget**
2. apt 官方源: `apt-get install nvidia-container-toolkit` → `E: Unable to locate package`; wget 配 `nvidia.github.io/libnvidia-container/stable/deb/ubuntu22.04` → `does not have a Release file` (路径 404)
3. GitHub release deb (wget): API 查 tag 成功 (v1.19.1) 但 `nvidia-container-toolkit_<v>-1_amd64.deb` 下载 0 字节/404 (CDN 受限); 版本名带 -1 修订号, 需 `browser_download_url` 精确匹配
- **替代方案 (不依赖 toolkit)**: `docker run --device /dev/nvidia0 --device /dev/nvidia-uvm --device /dev/nvidia-uvm-tools --device /dev/nvidiactl -v /usr/lib/x86_64-linux-gnu/libcuda.so.1:/usr/lib/x86_64-linux-gnu/libcuda.so.1:ro -v /usr/lib/x86_64-linux-gnu/libcudnn.so.8:... zmax-train ...` — 驱动在宿主机 (`nvidia-smi` 有输出) 时 torch.cuda 可用, 无需 toolkit; 验证: `docker run --rm --device ... zmax-train:latest nvidia-smi`

### 13.3 提交命令 (模型引擎 UI 内)
```python
# studio _start_remote_training + simulink on_train 远程分支一致:
"cd ~/lerobot-smolvla-lew && "
"if ! docker images -q zmax-train:latest >/dev/null 2>&1; then "
"echo BUILDING; nohup docker build -t zmax-train:latest . > /tmp/docker_build.log 2>&1 & "
"else docker run -d --rm --gpus all -v ~/lerobot-smolvla-lew:/app -w /app --name zmax_train "
"zmax-train:latest python -m lerobot.scripts.lerobot_train --config-path <cfg> "
"> /tmp/remote_train.log 2>&1; echo RUNNING; fi"
```
- BUILDING 分支: 日志"镜像构建中·完成后重跑", 不假报成功
- 存活验证: `docker ps --filter name=zmax_train --format {{.Names}}` + 日志无 Error/Traceback

## 14. 模型参数联动 (老倪: "模型选择了参数没变" — 三次修复)
1. 🐛 **dict.get 默认参数无条件求值 → KeyError**: `{"MLP":"x","专家":"y"}.get(name, {5模型}[name])` — Python 先求默认参数, 专家/MLP 不在默认 dict → KeyError 吞掉整个 _on_model_changed → 参数区"没变"
   - 修: `A.get(name) or B.get(name, "act")` 两级 get, 默认 dict 不索引 name
2. 🐛 **QSpinBox 无 decimals()** (QDoubleSpinBox 才有) — `spin.decimals() == 0` 抛 AttributeError 被吞 → 参数不更新
   - 修: `try: spin.setValue(val)  # float 先 (QDoubleSpinBox)` / `except: try: spin.setValue(int(val))` (QSpinBox)
3. 🐛 **config 的 lr 有缩进** (`  lr: 1e-4` 在 optimizer 下) — 正则必须 `^\s*{key}:` 否则 lr 读不到
4. **架构预设 ARCH_PRESET** (config 无这些 key): 每模型 obs/chunk/vlm/expert/width/freeze/wm/attn — **vlm/expert=0 的模型 (ACT/MLP/专家) 禁用对应控件** (`setEnabled(False)` + `setValue(w.minimum())`), 否则 setValue(0) 被 minimum clamp 显示旧值
5. 参数联动代码段**必须独立于 config 存在性** (config_mlp_distill.yaml 等可能不存在 → 放 if cfg 内则不执行 → 专家参数不动)

## 15. 结构条件 (几何条件改名 + 下放各模型行 — 老倪: "在YOLO之前不合理, 要体现潜在空间叠加")
- 老倪定名沿革: 坐标叠加 → 几何条件 → **结构条件** (2026-08-08 末)
- **下放**: 共享 1 个在感知链 (第0行) 被否 (老倪两次: "单独/在最前方/YOLO之前不合理") → **每模型行一个** (ACT/SmolVLA/LEW/VLA-Touch/AWE 5 个, 名带 "· 模型" 后缀区分), 布局列4 (视觉主干后), 连线 = `StateAdapter→🧩←视觉主干` → `🧩→后续解码` (latent += proj(state)×gate)
- 🐛 **共享定义 (无 · 后缀) 加载兜底创建**: 模板加载 `pos.get(nm)` 无布局位置 → 兜底单行创建 (x=520 孤点, 入0出0) → 但删定义会索引前移全乱 — **加载时跳过**: `if not cands and "结构条件" in nm and "·" not in nm: continue` (定义保留保索引, 不创建)
- 🐛 **布局列距 200** (x = 120 + col*200) — 列4 = 920, 不是 520 (列2); 验证位置断言用对列距
- 同名节点 (带 · 后缀) 布局精确匹配, 无模糊 — 行级定义必须与布局名完全一致
