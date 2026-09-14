# 2026-08-15 迁移到容器: 自检清单 + lark-oapi 手工安装配方

场景: 老倪说"你迁移到新家了, 检查系统自检"。新家是容器 (hostname 是容器ID,
root fs 为 overlay, 无 systemd, 无 /mnt 挂载, 无 GPU/docker/gh), 非原 WSL。

## 迁移后自检 (一次并行扫完)

1. skills_list → 116 个技能全在 (zmax/mlops 家族都在) ✅
2. ls ~/.hermes/memories/ → MEMORY.md + USER.md ✅
3. grep -oE '^[A-Z_]+' ~/.hermes/.env | sort -u → GITHUB_TOKEN/FEISHU_*/DEEPSEEK_API_KEY 键在 ✅
4. python 解析 ~/.hermes/cron/jobs.json → 4 个任务 enabled, ticker 心跳活跃 ✅
5. cat ~/.hermes/gateway_state.json → 显示旧家 pid/hermes_home, 是 stale 数据, 忽略
6. curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user → 200 MikeBMW ✅
7. 重建机器本地凭据: git config + ~/.git-credentials (从 GITHUB_TOKEN 写),
   ~/.zmax_ssh.json (ECS root@39.102.211.79 密码 Nix19789 从记忆恢复),
   apt install -y sshpass jq wget
8. sshpass ssh ECS 验证 → hostname + ls webroot 通 ✅
9. 飞书端到端: tenant_access_token → POST 测试消息到 dataworld chat_id → code:0 ✅

缺失但正常的: /mnt 无 Windows 挂载 (容器), 无 GPU, 无 docker/gh (需要再装)。

## 大坑: lark-oapi 依赖装不上 → gateway 卡 starting

症状链:
- gateway 日志: "Platform 'Feishu / Lark' dependencies missing — attempting install..."
- uv 自动安装挂起数分钟 (PyPI/aliyun 镜像都挂, 即使 --no-deps 也挂)
- gateway 看门狗: "missed 3 consecutive liveness probes" exit code 75 杀掉进程
- 手动 pip 也不行: uv 建的 venv 里**没有 pip 模块** (ModuleNotFoundError: No module named 'pip')

### 正确配方 (全部实测通过)

```bash
# 1. 从 aliyun simple index 拿真实 wheel URL (直接拼 /simple/<pkg>/<name>.whl 会 404 到 About us 页)
curl -sL "https://mirrors.aliyun.com/pypi/simple/lark-oapi/" | grep -oE 'href="[^"]*1\.6\.8[^"]*"'
# → ../../packages/4a/ad/.../lark_oapi-1.6.8-py3-none-any.whl  (注意是 packages/ 路径)

# 2. 下载 + 用 uv 装本地 wheel
curl -sL -o /tmp/lark_oapi-1.6.8-py3-none-any.whl "https://mirrors.aliyun.com/pypi/packages/4a/ad/.../lark_oapi-1.6.8-py3-none-any.whl"
/root/.hermes/bin/uv pip install --python /root/.hermes/venv/bin/python /tmp/lark_oapi-1.6.8-py3-none-any.whl
# 坑: wheel 文件名必须带 py3-none-any 标签, uv 报 "The wheel filename is invalid: Must have a Python tag"
```

### 若 uv 装本地 wheel 也挂 (本会话就发生了): 直接 tar 解包进 site-packages

```bash
SP=/root/.hermes/venv/lib/python3.11/site-packages
rm -rf $SP/lark_oapi $SP/lark_oapi-1.6.8.dist-info   # 清掉之前损坏的残留
python3 -c "import zipfile; zipfile.ZipFile('/tmp/lark_oapi-1.6.8-py3-none-any.whl').extractall('/tmp/lark_extract')"
# 坑: 直接 extractall 到 site-packages 或 cp -r 会超时/半途 (overlayfs 小文件慢), 先解到 /tmp 再 tar 单流复制:
cd /tmp/lark_extract && tar cf /tmp/lark.tar lark_oapi lark_oapi-1.6.8.dist-info
cd $SP && tar xf /tmp/lark.tar
# 验证: python -c "import lark_oapi"  (api 子模块应 59 个)
```

### import 慢 85 秒 → 飞书连接 30s 超时

- lark_oapi 有 11117 个文件, overlayfs 上首次 import 要编译/加载 ~85s
- gateway 默认 platform_connect_timeout=30s → "feishu connect timed out after 30s", state=retrying
- 修: `hermes config set gateway.platform_connect_timeout 300` 然后重启 gateway
- 预编译 pyc 能缓解 (python -m compileall -q -j 4 .../lark_oapi/), 但 import 仍 ~85s, 关键是调大超时
- 启动 gateway 后要等 1-2 分钟才看到 "connected to wss://msg-frontier.feishu.cn" — 属正常, 别急着杀

## 追加坑 (2026-08-15 同日二次验证)

- **gateway 必须用 `~/.hermes/venv/bin/hermes gateway run` 启动** — 不要用
  `~/.hermes/hermes-agent/venv/bin/python` (源码树 venv): 那个 venv 里 lark_oapi
  是损坏残留 (`ModuleNotFoundError: No module named 'lark_oapi.api.apaas'`),
  lazy_deps 的 check_feishu_requirements 判定不满足 → 触发 uv 自动安装 →
  PyPI/aliyun 镜像挂起 → shutdown_watchdog "missed 3 liveness probes" exit 75 杀进程。
  确认方式: `ls ~/.hermes/logs/gateway-exit-diag.log` 看历史 gateway.start 的 argv。
- **容器重启后 gateway 进程会丢** (容器无 systemd, 无自愈) — 每次容器重启后要手动
  重新 `~/.hermes/venv/bin/hermes gateway run` (background), 等 2-5 分钟
  (lark_oapi import ~85-150s + 连接), 看到 `connected to wss://msg-frontier.feishu.cn`
  才算好。启动前 rm -f ~/.hermes/gateway.lock ~/.hermes/gateway.pid (stale)。
- **容器无 /mnt、无 GPU、无 docker、无 ping** — 旧家数据搬迁走 HTTP 方案:
  旧家 WSL 起 `python3 -m http.server 8000 --bind 0.0.0.0`, 容器 curl 拉 (HTTP 目录
  列表可盘点)。容器网段 172.17.x, 旧家 WSL 172.18.80.x, TCP 互通。打包用 tar 单流。

## 教训

- uv 建的 venv 无 pip 模块 → 一律走 `~/.hermes/bin/uv pip install --python <venv>/bin/python`
- 容器 overlayfs 复制大量小文件: 用 tar 单流, 不用 cp -r / extractall
- gateway 启动慢是 lark_oapi 的锅, 不是挂了; platform_connect_timeout 是必改项
