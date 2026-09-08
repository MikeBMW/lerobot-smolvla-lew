# Mac 端部署: arm64 容器构建 (2026-08-09 实测)

用户需求链: VEH.2.31「📥 推送到 Orin」= 把**带模型的容器**推到 Mac(小芳端), Mac Docker 就绪后
原生 arm64 构建 + 模型内置/挂载 → 推理; Orin 后续同镜像 push(先不动, 用户拍板"在 MAC 部署成功即可")。

## 链路(最终定稿)

```
[4060] 模型 safetensors → scp ECS /www/wwwroot/datadrive.world/models/ (act_latest.safetensors 覆盖即部署)
  → chmod 644 (scp 保留 600 → nginx www 读不了 → 403!)
  → relay POST /command 下发 Mac 指令 (Mac 守护轮询 command.json 执行)
  → Mac: git clone 仓库 → docker build --target infer (原生 arm64) → curl 模型 → docker run 推理
```

## ⚠️ arm64 镜像构建: 别在 x86 服务器交叉编译, 让 Mac 原生构建

**在 4090 (amd64) 上 buildx 交叉编译 arm64 的三个坑**:
1. **buildx 插件可能没装**: `docker: unknown command: docker buildx` → `apt-get install -y docker-buildx`
   (Ubuntu 22.04 包名 `docker-buildx`, 装完 `docker buildx version` 验证)
2. **无 qemu 模拟器 → `exec format error`**: buildx 交叉构建要在 x86 宿主跑 arm64 二进制,
   需 qemu-user-static + binfmt: `apt-get install qemu-user-static binfmt-support` +
   `docker run --rm --privileged multiarch/qemu-user-static --reset -p yes`。
   没装 → base 阶段 `RUN apt-get update` 报 `exec /bin/sh: exec format error` exit 255。
   国内服务器 apt 装 qemu 可能超时(源慢)。
3. **结论**: 与其在 x86 上折腾 qemu 交叉编译(慢 + 网络坑), **Mac 是原生 arm64, `docker build --target infer`
   直接原生编译最快最稳** —— 部署链路设计成"模型传 ECS + 指令通知 Mac 本地构建", 不传容器 tar。

### 补充: x86 本地(4060) 交叉编译 arm64 实操路径（2026-08-09 本地实测——被迫本地建时用）

如果 Mac 侧没有 git clone 条件/需要本地出 tar, 本地 4060 也能交叉编译（慢但可行）:
```bash
# ① buildx 插件: apt 源 docker-buildx 常 Ign(下载失败) → ghfast.top 镜像下 release 二进制
sudo curl -sL -o /tmp/buildx "https://ghfast.top/https://github.com/docker/buildx/releases/download/v0.14.0/buildx-v0.14.0.linux-amd64"
sudo mkdir -p /usr/libexec/docker/cli-plugins && sudo cp /tmp/buildx /usr/libexec/docker/cli-plugins/docker-buildx && sudo chmod +x ...
# ② arm64 binfmt 模拟器 (tonistiigi 比 multiarch 镜像小; WSL2 无 qemu-aarch64-static 时必需)
sudo docker run --privileged --rm tonistiigi/binfmt --install arm64
# ③ 多平台构建器 (--use 激活; inspect --bootstrap 首次要拉 buildkit 镜像, 等 running)
sudo docker buildx create --name multi --platform linux/amd64,linux/arm64 --use
sudo docker buildx inspect multi --bootstrap   # 等 Status: running 再构建
# ④ 构建 + 本地加载 (--load 只在构建器单平台时可用)
sudo docker buildx build --platform linux/arm64 --target infer -t zmax-infer:arm64 --load -f docker/Dockerfile .
```
**交叉构建的两个新坑**（实测）:
- **实测成功（2026-08-09 本地 4060 完整跑通）**: buildx + binfmt 装好后 `--platform linux/arm64 --target infer --load` 成功出 `zmax-infer:arm64`（6.25GB, torch 2.11.0+cpu, 模型内置 /app/models/act/）——依赖 pin 对后 QEMU 15-30 分钟出镜像, 本地交叉编译是可用路径, 不必等 Mac 原生构建
- **模型 COPY 进镜像时 `.dockerignore` 必须放行 outputs/ 具体目录**: 构建报
  `failed to compute cache key: ... "/outputs/train/xxx/pretrained_model": not found` ——
  不是文件缺失, 是 `.dockerignore` 的 `outputs/` 排除了它。放行:
  `outputs/*` + `!outputs/train/<dir>/checkpoints/<step>/pretrained_model/`
  (注意 `!` 只能重新包含目录本身, 内容需目录级放行——同 site-packages 放行逻辑)
- **torch arm64 CPU wheel 下载 + QEMU 模拟 apt 都很慢**: base 阶段 apt 装系统依赖
  (ffmpeg/glib 等) 在模拟下每步几十秒~几分钟, 全程 15-30 分钟是正常量级, 别中途判断卡死。
- **arm64 依赖装不上先猜版本冲突——用 `--only-binary :all: --dry-run` 在 arm64 容器里试装**
  （2026-08-09 实测）: QEMU 交叉构建 `pip install -r requirements.lock` 失败
  `subprocess-exited-with-error` 且日志不显示是哪个包时, 直接在 arm64 容器里 dry-run 逐批试:
  ```bash
  sudo docker run --rm --platform linux/arm64 --entrypoint pip python:3.12-slim \
    install --only-binary :all: --dry-run transformers==5.5.4 accelerate==1.14.0 ... 2>&1 | grep -iE 'error|conflicting'
  # 实测抓到: huggingface-hub==0.36.0 and transformers==5.5.4 conflicting dependencies
  # (transformers 5.5.4 要求 huggingface-hub<2.0,>=1.5.0 → lock 的 <0.37 是错的)
  ```
  排查顺序: 先单独 dry-run 核心包(transformers 等)看它要求的依赖范围 → 再全量 dry-run 找冲突对。
  **tokenizers 0.21.4 等 rust 包在 arm64 有预编译 wheel**（--only-binary 可装）, 别误以为是编译失败。
  **最终 lock 三个 arm64 关键 pin（2026-08-09 交叉构建 4 轮排错定稿）**:
  - `huggingface-hub>=1.5.0,<2.0`（transformers 5.5.4 要求 `>=1.5.0`; 旧 lock `<0.37` → ResolutionImpossible）
  - **`tokenizers==0.22.2`**（transformers 5.5.4 要求 `>=0.22.0,<=0.23.0`; lock 的 0.21.4 → `Cannot install ... and tokenizers==0.21.4 conflicting dependencies`。查法: `pip install --only-binary :all: --dry-run transformers==5.5.4 2>&1 | grep tokenizers` 直接看它要求的范围）
  - **`av==14.1.0`**（`av>=13.0,<15` 会让 pip 解析到无 arm64 wheel 的版本 → `Getting requirements to build wheel: finished with status 'error'` 源码编译失败; 14.1.0 有 aarch64 wheel, --only-binary dry-run 验证通过）
  **规则: lock 里所有带范围约束的包 (`>=,<`) 在交叉构建前先逐个大版本 dry-run 确认 arm64 wheel 存在, 直接 pin 到有 wheel 的精确版本**, 别让 pip 自己选（QEMU 下源码编译几乎必失败）。
- Dockerfile 多阶段默认 build **所有阶段**——`--target infer` 只构建目标阶段,
  否则 infer 残留旧 torch(如 2.4.1) 白拉 797MB 且与 train 的 2.11.0 冲突。

## 部署完成的验证方法（ECS nginx 日志看 Mac 拉取, 2026-08-09 实测）

部署是否真的开始, 不看本地日志——**查 ECS 访问日志里 Mac 的请求**:
```bash
sshpass -p ... ssh root@39.102.211.79 \
  'grep -E "models/act|safetensors" /www/wwwlogs/datadrive.world.log | tail -5'
# 期望看到: GET /models/act_latest.safetensors 200 (正在下载, size_download 递增)
#           HEAD /models/act_<新时间戳>.safetensors 200 (Mac 守护在检查最新模型)
#           GET ... 206 分片 (断点续传下载)
```
- 206 = Mac 端 curl 断点续传分片下载, 是"正在拉"的铁证; 200 且 size_download 固定 = 已拉完
- 上传后必做 `chmod 644`（scp 保留 600 → nginx www 读不了 → 403, 小芳拉取报 403 先查权限）
- 最新一个文件的权限最容易漏（上传脚本只修了 act_latest 的, 时间戳版可能是 600）——上传即 chmod, 别等拉取报错
- **⚠️ 控制台日志声称"已部署完成"≠ 真部署（2026-08-09 老倪"这个信息准确么？我要看实际的路径"实测）**：
  日志显示"✅ 已上传 act_latest / 📡 已下发 Mac 部署指令 / 🤖 Mac 守护已部署 / 部署完成"——但
  SSH 到 ECS 核实发现: ① `ls models/` 无 act_latest（声称上传的文件没落盘）② 部署指令引用的
  `act_20260809_144512.safetensors` 不存在（实际是 144640）③ 容器 tar 也没上传。**根因**: 上传脚本
  scp 失败/路径错时仍打"已上传"日志, 且多端(web/飞书端)并发写 models/ 互相覆盖。
  **铁律: 部署状态以 ECS 实际文件 + nginx 访问日志为准**——`ls -la /www/wwwroot/datadrive.world/models/`
  看真实文件/权限/时间戳, `grep 'models/act' /www/wwwlogs/datadrive.world.log | tail` 看 Mac 是否真在拉;
  别信控制台/守护的"完成"声称。发现缺文件就手动 scp 补传 + chmod 644（一次到位）。



## 为什么传模型不传容器 tar

- 本地 zmax-std 镜像 28GB (x86_64), 不能直接给 arm64 Mac; buildx 交叉产物 tar 也有 1-2GB
- ECS 数据盘 /dev/vda3 仅 40G, 剩 ~8G → 放不下大 tar; 模型 safetensors 87MB 绰绰有余
- .dockerignore 排除 `outputs/` → 模型本来就不在镜像里, 推理靠 `--ckpt` 参数/挂载

### ⚠️ 大 tar 传 ECS 实测是死路（2026-08-09 交叉产物 6.25GB 全链路失败证据）

本地交叉构建出 arm64 infer 镜像（6.25GB, 含模型内置 /app/models/act/）后想 save→tar→ECS→Mac 拉取,
**完整踩死的路径, 别重复**:

1. **`docker save | gzip` 几乎不缩小**（6.25GB → 5.9GB tar.gz）——镜像层本身已压缩, 别指望 gzip 省空间
2. **WSL 的 /tmp 是 tmpfs 7.8G**: tar.gz 5.9G 放得下, 但 `split -b 900M` 分块到 /tmp **报
   `input/output error: no storage space`**（分块总和超 tmpfs）→ 分块必须输出到 /home（712G 足）
3. **分块 scp 到 ECS 全部 `Connection closed`**: 900M 块连传 3 块全断（端口 22 和 23 都试过,
   `ServerAliveInterval=30` + `timeout 400-590` 也救不了）；小文件（100M 级）正常 → ECS 对
   ~900M 级 scp 连接直接掐。且 SSH 失败过多会**短暂锁 IP**（`Permission denied (publickey,password)`
   连正确密码都拒）——连续 scp 失败后先停 1-2 分钟再探测 `ssh host 'echo OK'`
4. **大文件换通道**: 只有 ~100M 级以下 scp 稳。大文件要么 web 端 4090 有专门上传通道, 要么
   ECS 侧开 HTTP 上传接口（php post_max_size/nginx client_max_body_size 都要调）, 要么放弃传 tar
   ——**模型 safetensors 87MB 走 scp 完全没问题, 容器让 Mac 本地原生构建**（本 ref 主方案）

### ✅ 小文件 scp 也断时——base64 走 SSH 直写（2026-08-09 实测, 7.7KB JSON 上传）

ECS 的 scp 限制不只是"~900M 断"——**偶发连 7.7KB 的 JSON 也 `Connection closed`**（同一端口 23,
限流可能看连接频次）。此时**别死磕 scp**，用 base64 经 ssh 命令直写（小文件 10KB 级完全可行）：
```bash
# 本地: base64 编码（单行, 无换行）
python3 -c "import base64; open('/tmp/f.b64','w').write(base64.b64encode(open('file.json','rb').read()).decode())"
# 远端: echo 进管道解码落盘（注意命令里 $(cat) 展开, 文件大时要拆多条 echo 追加）
sshpass -p ... ssh root@39.102.211.79 \
  "mkdir -p /www/wwwroot/datadrive.world/scenes && echo '$(cat /tmp/f.b64)' | base64 -d > /www/wwwroot/datadrive.world/scenes/f.json && chmod 644 ..."
# 验证: ls -la 看字节数与源一致 + head -c 100 看内容头（JSON 首字符 {）
```
- base64 会膨胀 ~33%（7.7KB → 10.3KB 单行命令），10KB 级没问题；几十 KB 以上拆多段 echo 追加
- 落盘后**必须 chmod 644**（echo 管道创建默认 600 root，nginx www 读不了 → 403）
- 验证字节数 `ls -la | awk '{print $5}'` 与源文件一致，再 `head -c 100` 看内容首字符，双确认

**结论: 传模型不传容器 tar 不仅是空间考虑, 更是 ECS scp 连接限制的硬约束。**

## relay /command 下发 Mac 指令(已有机制复用)

- ECS relay `POST /api/relay/command` `{"cmd": "..."}` → 写 `/root/zmax-relay/command.json` →
  Mac 守护(hermes_gateway_mac)轮询 GET /command 执行。4060 下发示例:
  `deploy_mac: git clone https://github.com/MikeBMW/lerobot-smolvla-lew.git && cd ... && docker build --target infer -t zmax-std:1.0-infer -f docker/Dockerfile . && curl -s https://datadrive.world/models/act_latest.safetensors -o /tmp/act_latest.safetensors && echo READY`
- 验证落盘: `sshpass -p ... ssh root@39.102.211.79 "cat /root/zmax-relay/command.json"`

## Mac/Orin 环境事实(小芳确认 2026-08-09)

- Mac: Docker 24.0.5 (Docker Desktop), arm64, 磁盘 118G 可用, `docker run hello-world` 通过 → 完全就绪
- Orin: Docker 29.6.2 已装但**当前用户 tashan 不在 docker 组** → `sudo usermod -aG docker tashan; newgrp docker`
  授权后才能用 (小芳提供命令, 用户拍板 Orin 先不动)

## GUI 侧实现(studio.py TrainingModule)

- VEH.2.31 部署模型下拉(`deploy_model_combo`, registry 已保存模型, ACT 优先在首) + 「📥 推送到 Orin」按钮
- **按钮联动铁律**: 推送按钮初始 `setEnabled(False)`, 只有点选「📱 端侧部署」模式卡
  (`_ct_pick("deploy")`) 才启用 → `self.btn_deploy_orin.setEnabled(key == "deploy")`
  —— 用户报"点击没反应"多半是按钮禁用态(没选端侧部署模式)
- `_deploy_model_to_orin` 后台线程: 选模型(下拉→ckpt_edit→registry) → scp 上传模型(版本化+act_latest)
  → chmod 644 → HEAD 验证 URL → 检查容器 tar 就绪 → POST /command 通知 Mac → 日志显示全链路

## 模型源选择优先级(下拉 → 编辑框 → registry)

```python
pm = None
sel = self.deploy_model_combo.currentData()   # ① 下拉选中
if sel and os.path.isdir(sel): pm = sel
if not pm:                                    # ② 模型引擎 ckpt_edit 文本
    p = self.ckpt_edit.text().strip()
    if p and os.path.isdir(p): pm = p
if not pm:                                    # ③ registry 最新 ACT
    reg = json.load(open(reg_path)); [item for item in reg if item.get("policy")=="act"]
```
