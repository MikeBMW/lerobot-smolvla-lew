# GPU 容器 venv 断链修复实录 (2026-08-19)

## 场景
- 两个容器共享持久卷 `/root/.hermes` + `/workspace`（D:/hermes-docker/.hermes）
  - hermes-ubuntu（无 GPU，本会话所在容器）
  - hermes-ubuntu-gpu2（`--gpus all`，ubuntu:24.04 裸容器）
- 用户从 Windows PowerShell `docker exec -it hermes-ubuntu-gpu2 bash` 进入 GPU 容器，启动 Hermes 失败。

## 现象链
1. `hermes: command not found` → PATH 没配（bashrc 追加后当前会话不生效，需 `export` 或新会话）
2. `export PATH=/root/.hermes/venv/bin:$PATH && hermes` →
   `bash: /root/.hermes/venv/bin/hermes: cannot execute: required file not found`
   （脚本存在、PATH 对，但解释器起不来 — 区别于 `command not found`）

## 根因
uv 创建的 venv 中 `venv/bin/python` 是符号链接：
```
/root/.hermes/venv/bin/python -> /root/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11
```
- `/root/.local` 不在共享卷（只有 `/root/.hermes` 和 `/workspace` 持久）
- GPU 裸容器没有该路径 → 整条链接链断 → "required file not found"
- venv site-packages 是 3.11 编译的，不能拿容器自带 python3（ubuntu 24.04 = 3.12）重链

## 修复（一次永久，重启不复发）
```bash
# 共享卷里有 uv
/root/.hermes/bin/uv --version

# 1. 把 python 3.11 装进共享卷（不装 /root/.local）
export UV_PYTHON_INSTALL_DIR=/root/.hermes/uv-python
export UV_LINK_MODE=copy
/root/.hermes/bin/uv python install 3.11

# 2. 重链 venv 的 python
PY_DIR=$(ls -d /root/.hermes/uv-python/cpython-3.11*/ | head -1)
ln -sf "${PY_DIR}bin/python3.11" /root/.hermes/venv/bin/python

# 3. 验证
/root/.hermes/venv/bin/hermes --version
```
自动化脚本已落盘：`/root/.hermes/gpu2_fix_python.sh`（GPU 容器里 `bash /root/.hermes/gpu2_fix_python.sh` 一条跑完）。

## 关键环境事实（双容器架构）
- Hermes 本体 = `/root/.hermes/venv/bin/hermes`（共享卷），Python 3.11.15，v0.20.1
- 配置/密钥/技能/记忆全在 `/root/.hermes`（.env、config.yaml、skills、memories）
- GPU 容器启动 Hermes：`echo 'export PATH=/root/.hermes/venv/bin:$PATH' >> ~/.bashrc` 然后 `hermes`
- 容器重启清 `/root`，但 `.hermes`/`workspace` 卷不丢
- 训练环境恢复：`bash /root/.hermes/backup/restore.sh`（clone 仓库 + metaworld 数据 + gui-venv311 + torch cu128）
- GPU 容器训练依赖安装：`bash /root/.hermes/gpu_install.sh`（-e .[all] 后强制重装 torch cu128）
