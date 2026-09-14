# 端侧部署链路 + GUI 代码结构坑 (2026-08-09 会话沉淀)

VEH.2.26/VEH.2.31 端侧部署功能实现过程中的全部实测根因。与 remote-training-debugging.md 互补 (那边是训练/拉回, 这边是部署到 Mac/Orin + GUI 控件开发坑)。

## 1. 仓库根路径 = 3× dirname (studio.py 专属铁律) — 空下拉/空目录的头号隐形根因
- `tools/gui/studio.py` 里 `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 只到 **tools/** 层, **不是仓库根**!
- 仓库根需要 **3 层**: `os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` (gui→tools→repo_root)。
- 症状: 读 `models/saved/registry.json` 拼出 `.../tools/models/saved/...` → exists=False → 下拉显示"无已训练模型"/路径空, **不报错** (except 吞掉)。
- 全文件已有 3 层写法 (1084/1772/5100 等) — 新增代码必须照抄 3 层, 不要凭感觉写 2 层。
- 验证: offscreen 实例化模块后打印 `_saved_registry_path()` 或直接 `os.path.exists(reg_path)`。

## 2. 方法定义在错误的类 → AttributeError 被 except 吞 → 控件静默为空
- 症状: QComboBox 构建时调用 `self._refresh_deploy_models()`, 但该方法定义在 **InferencePanel** (studio.py 7871 类), 调用方是 **TrainingModule** (2244 类) → `AttributeError` → 被 `try/except: pass` 吞 → 下拉永远空, 无任何报错。
- 根因: 大文件 (studio.py 9000+ 行) 里 patch 时方法落在错误类作用域。`grep -n 'class ' + grep 'def _xxx'` 对比行号区间即可确认。
- 修复: 方法移入正确类; 删除重复定义 (否则同名方法残留混淆)。
- 排查法: offscreen 直接调 `mod._refresh_deploy_models()` (不包 try) → AttributeError 立刻现形; 别信"逻辑单独跑是对的"。

## 3. VEH.2.26 部署模型下拉 (deploy_model_combo)
- 位置: 模式卡片行 (train/infer/deploy 三卡) 之后, `cv.addLayout(deploy_row)`。
- 填充: `_refresh_deploy_models()` 读 registry.json, 过滤 `os.path.isdir(base/checkpoints/last/pretrained_model)`, **ACT 排第一** (用户要求默认第一个):
  `items.sort(key=lambda x: (0 if x[0] == "act" else 1,))`
- 注意: TrainingModule 内不要用 `self._saved_registry_path()` (那是 InferencePanel 的方法, 见 §2), 直接拼 3 层 dirname 路径。

## 4. VEH.2.31 「📥 推送到 Orin」按钮 — 端侧部署高亮才可点
- 用户要求: **只有端侧部署模式卡选中 (高亮) 后才能点击**。
- 实现: 构建时 `setEnabled(False)`; `_ct_pick(key)` 里 `self.btn_deploy_orin.setEnabled(key == "deploy")`。
- ID 悬停: `_veh2_apply` 按布局位置自动编号 (VEH.2.xx) + `hover_only=True` tooltip — 新控件无需手动注册, 自动获得悬停 ID。

## 5. 模型部署到 Mac/Orin — 静态 URL 覆盖即部署 (用户拍板链路)
- 链路: `[4060] → 模型safetensors上传 ECS 静态URL → /command 下发 Mac → Mac 拉取/构建 → Orin`。
- 静态 URL 基础设施 (web 分身已配好, 勿重建):
  - nginx `location ^~ /models/` → `root /www/wwwroot/datadrive.world;` (宝塔站点 datadrive.world.conf)
  - 模型目录 `/www/wwwroot/datadrive.world/models/`, 公开 URL `https://datadrive.world/models/<name>.safetensors`
  - 约定: `act_latest.safetensors` = 覆盖即部署 (Orin/Mac 轮询哈希变化); `act_<ts>.safetensors` = 版本化保留。
- **chmod 644 铁律**: scp 上传保留本地 600 权限 → nginx www 用户读不了 → **HTTP 403**。上传后必须 `chmod 644`。`ls -la` 看到 `-rw-------` 就是它。
- **PUT 405**: nginx 静态目录只读, `requests.put()` 返回 405 → 必须走 scp (`sshpass scp ... root@39.102.211.79:/www/wwwroot/datadrive.world/models/`)。
- 验证 URL: `curl -sI https://datadrive.world/models/act_latest.safetensors` → 200; 支持 Range (206) → Orin 断点续传友好。
- ECS 凭据: root@39.102.211.79 (sshpass), relay 在 /root/zmax-relay/, 磁盘 40G 只剩 ~8G — **大文件 (容器 tar) 不能经 ECS**, 只传模型小文件。

## 6. Mac 容器部署 — 交叉构建 vs 原生构建
- 用户原话"将训练好带模型的容器 docker 推到 MAC 上", 小芳 Mac 确认: Docker 24.0.5 + arm64 + 118G 就绪, Orin Docker 29.6.2 需 `sudo usermod -aG docker tashan` (tashan 不在 docker 组, permission denied)。
- **4090 交叉构建 arm64 的坑**: 
  - 4090 默认无 docker buildx → `apt-get install docker-buildx` (0.20.1)。
  - 无 qemu arm64 模拟器 → buildx 跑 arm64 base 层报 `exec /bin/sh: exec format error` → 需 `qemu-user-static binfmt-support` + `docker run --rm --privileged multiarch/qemu-user-static --reset -p yes` (apt 装 qemu 可能网络超时)。
- **最优路径: Mac 原生构建** (arm64 本机 docker build 无需 qemu, 快得多):
  下发 /command 给 Mac: `git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git && cd ... && docker build --target infer -t zmax-std:1.0-infer -f docker/Dockerfile . && curl -s https://datadrive.world/models/act_latest.safetensors -o /tmp/act_latest.safetensors && echo READY`
  (仓库 .git 350MB, clone 可接受; Dockerfile infer target 是 arm64 CPU wheel + `COPY . /app`, `.dockerignore` 排除 data/outputs/reports → 镜像 ~1GB, 不内置模型, 模型挂载/单独拉取)。
- relay `/command` 端点: POST `https://datadrive.world/api/relay/command` `{"cmd": "..."}` → 写 command.json → Mac 守护轮询执行。GET /command 可查当前指令。

## 7. 部署按钮完整动作链 (studio.py `_deploy_model_to_orin`)
1. 模型源: `deploy_model_combo.currentData()` (下拉选中) → `ckpt_edit` → registry 最新 ACT。
2. 取 `model.safetensors` (87MB), scp 上传 ECS models/ (版本化 + act_latest), chmod 644。
3. HEAD 验证 `https://datadrive.world/models/act_latest.safetensors` 200。
4. HEAD 检查 `zmax-infer-arm64.tar` (容器 tar) 是否就绪。
5. POST /command 下发 Mac: `deploy_model act <ver> <tar>`。
- 全后台线程 (daemon=True), 日志逐步 `self._log` — 用户要求"看到路径, 看到实际上传过程"。

## 8. 经验: 先问链路再动手
- 用户两次澄清部署语义: 先以为"上传 ECS 静态 URL" → 用户贴小芳消息明确"带模型的容器 docker 推到 MAC" → 又要"MAC 部署成功即可 (Orin 先不动)"。
- 教训: 部署类功能先确认目标端 (Mac/Orin)、传输介质 (单文件 vs 容器 tar)、用户验收标准 (Mac 跑通即可), 再写代码; 已写错的代码用 execute_code 整段替换 (patch 在大方法上会缩进错乱, 见下)。

## 9. 大方法替换 — 用 execute_code 整段重建, 不用 patch
- 对 100+ 行方法做语义替换时, patch 的 old/new 匹配容易产生**嵌套缩进错乱** (方法套方法, 语法仍 OK 但逻辑全错)。
- 安全法: `si = src.find("    def _deploy_model_to_orin(self):"); ei = src.find("    def _start_training(self):", si); src = src[:si] + new_method + src[ei:]`, 再 `ast.parse` 验证 + offscreen 冒烟。
