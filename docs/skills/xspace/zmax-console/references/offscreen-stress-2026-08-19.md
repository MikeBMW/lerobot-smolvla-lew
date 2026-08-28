# offscreen 压测 + GPU 容器恢复 (2026-08-19 实测)

## stress_offscreen.py 压测 (v2.1.5 起)

用途: 模拟用户操作 (切画布/双击模式开关/FeatureList 弹窗/强制重绘/模式切换, 每 2s 一步) 验证
Segfault 是否 X11/VcXsrv 层问题。offscreen 平台零崩溃 = Qt/代码层稳定, 崩在 X11 层。

```bash
cd tools/gui
QT_QPA_PLATFORM=offscreen python3 stress_offscreen.py          # 默认 10 分钟
QT_QPA_PLATFORM=offscreen python3 stress_offscreen.py --minutes 2   # 参数化 1-60
# 退出码 0 = 存活到结束; 非 0 = 崩溃/异常
```

**实证 (2026-08-19)**: 10 分钟 299 步零崩溃 (代码层稳定); 之前 VcXsrv 崩 2 次 → 弃用,
Xvfb :99 + x11vnc :5900 为默认显示通道。

**⚠️ 坑: 压测会污染画布 JSON** — 模拟双击模式开关触发 `_toggle_mode` 持久化写回
(a72bb04 模式开关持久化功能) → flows/*.json 的 mode 字段被改。v2.1.5 修复:
脚本启动时备份 flows/ 全部 json 到 /tmp/flow_backup_*, atexit 注册恢复。
注意: SIGSEGV 时 atexit 不执行, 崩溃后调用方需 `git checkout flows/` 兜底恢复。

**裸容器跑压测前置** (PyQt5 ImportError: libGL.so.1):
```bash
apt-get install -y libgl1 libglib2.0-0 libdbus-1-3 libfontconfig1 libxkbcommon0
```

## GPU 容器 (hermes-ubuntu-gpu2) 环境恢复要点

- 容器是裸 ubuntu:24.04: 先 `apt-get install git python3 python3-pip python3-venv` (aliyun 源), 再 `bash /root/.hermes/backup/restore.sh` (clone 仓库 + venv + torch cu128)。
- **credential.helper 被 VSCode 覆盖**: VSCode Dev Containers 注入 `!f(){...vscode git-credential-helper...}` 作 --global helper 且优先 → push 报 "could not read Username"。修复: `git config --global credential.helper store` (覆盖 VSCode helper), .git-credentials 照常生效。
- push 凭据重建: `TOKEN=$(grep -oP '(?<=^GITHUB_TOKEN=).*' /root/.hermes/.env | head -1)` → `printf 'https://MikeBMW:%s@github.com\n' "$TOKEN" > /root/.git-credentials && chmod 600`。
- 缺 curl 时建 GitHub Release 用 python urllib (POST /repos/MikeBMW/lerobot-smolvla-lew/releases, Authorization: token)。
