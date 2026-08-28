# Z-MAX Console Docker 容器化

## 方案 A — X11 主机 socket 挂载（轻量）

**Dockerfile**: `tools/gui/Dockerfile`
- Base: `python:3.12-slim`
- Qt/X11 运行时依赖: `libxcb-xinerama0, libxkbcommon-x11-0, libgl1-mesa-glx, libegl1-mesa, libdbus-1-3, fontconfig`
- Python 包: `PyQt5, numpy, pillow`
- 非 root 用户运行 (ARG UID/GID)
- 入口: `studio.py`（通过 CONSOLE_MODE 环境变量切换）

**构建+运行（WSL2/WSLg — 推荐）:**
```bash
# 构建
docker build --build-arg UID=$(id -u) --build-arg GID=$(id -g) -t zmax-console tools/gui/

# 运行（WSLg 自动接管窗口）
docker run --rm -e DISPLAY=$DISPLAY -e CONSOLE_MODE=studio \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $HOME/.hermes:/home/xspace/.hermes:ro \
    zmax-console

# 一行命令（自动构建+运行）
bash tools/gui/docker-run-oneliner.sh
```

**运行（Windows Docker Desktop + VcXsrv — 无 WSL）:**

当用户只有 Docker Desktop for Windows（Hyper-V 模式），没有 WSLg：

1. 装 [VcXsrv](https://sourceforge.net/projects/vcxsrv/)（Windows X Server）
2. 启动 XLaunch → 勾选 "Disable access control"
3. 容器内通过 `host.docker.internal` 连 Windows X Server（不再需要 `-v /tmp/.X11-unix`，Docker Desktop 不走 UNIX socket）

```bash
docker run --rm \
    -e DISPLAY=host.docker.internal:0 \
    -e CONSOLE_MODE=studio \
    zmax-console
```

**GPU 加速（可选）:**
```bash
docker run --rm --gpus all \
    -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
    zmax-console
```
需要提前装好 NVIDIA Container Toolkit。

## 国内分发 — 阿里云 ACR

Docker Hub 在国内被墙/限速。使用阿里云容器镜像服务（ACR）个人版，免费，同账号内网免流量。

**仓库地址:**
```
registry.cn-hangzhou.aliyuncs.com/zmax/console
```

**使用:**
```bash
# 登录（需要先开通 ACR 个人版）
docker login registry.cn-hangzhou.aliyuncs.com
# 用户名: 阿里云账号全称
# 密码:   容器镜像服务独立密码（控制台设置）

# 拉取
docker pull registry.cn-hangzhou.aliyuncs.com/zmax/console

# 运行
docker run --rm -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    registry.cn-hangzhou.aliyuncs.com/zmax/console
```

## CI 自动构建 — GitHub Actions

工作流文件: `.github/workflows/docker-console.yml`

**触发条件:**
- 推送 `v*` tag（如 `v1.0.6`）
- 手动触发（workflow_dispatch）

**自动完成:**
1. Buildx 多架构
2. 推送到 ACR（`registry.cn-hangzhou.aliyuncs.com/zmax/console`）
3. 打两个 tag: `{版本号}` + `latest`

**GitHub Secrets 要求（需用户手动设置）:**

| Secret | 值 |
|---|---|
| `ACR_USERNAME` | 阿里云容器镜像服务登录名 |
| `ACR_PASSWORD` | 阿里云容器镜像服务密码 |

**触发流程:**
```bash
git tag v1.0.6 && git push origin --tags
# → Actions 自动构建推送到 ACR
```

## 方案 B — noVNC 浏览器访问（待实现）

如果想脱离桌面环境，改为方案 B：容器内跑 TigerVNC + noVNC，浏览器访问 `<host>:6080` 看到 GUI。适用于 4090 训练机（无显示器）。

## 注意事项

- 容器内用 GPU 需要 `--gpus all` + NVIDIA Container Toolkit
- `~/.hermes` 以只读卷挂载，studio.py 可读记忆文件但不能写
- 宿主机 uid/gid 需匹配（ARG UID/GID 解决文件权限问题）
- **YAML 坑**: PyYAML 把非引号的 `on:` 解析为布尔值 `True`。GitHub Actions 工作流文件中的 `on:` 要用引号写成 `"on":`，否则本地 `yaml.safe_load()` 验证会失败。GitHub 自己的解析器不受影响。
