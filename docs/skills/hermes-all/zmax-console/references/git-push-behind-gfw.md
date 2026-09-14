# GitHub 被墙 push 绕过 (U盘/无梯子环境)

2026-08-22 首次实测, 2026-08-25 更新 (ghfast.top 已超时作废 → ghproxy.net)。

## 现象
```bash
git push origin main
# fatal: unable to access 'https://github.com/...': GnuTLS recv error (-110): The TLS connection was non-properly terminated.
```
= github.com 直连被墙 (TLS 连接被中断)。`curl -sI https://github.com` 也大概率不通。

## ⚠️ 镜像当前状态 (2026-08-25)
- **ghproxy.net ✅ 当前可用** (push 走这个)
- **ghfast.top ❌ 已超时作废** (08-25 起 push 卡死超时)
- api.github.com ✅ 可直连 (Release 用 API 上传)

## 方案
remote url 配 ghproxy.net 镜像。用 **URL 内嵌 token 一次性 push** (不改 ~/.git-credentials 文件, token 不落配置文件):

```bash
TOKEN=$(grep -oP 'ghp_[A-Za-z0-9]+' ~/.git-credentials | head -1)
git push "https://MikeBMW:${TOKEN}@ghproxy.net/https://github.com/MikeBMW/lerobot-smolvla-lew.git" main
git tag vX.Y.Z
git push "https://MikeBMW:${TOKEN}@ghproxy.net/https://github.com/MikeBMW/lerobot-smolvla-lew.git" vX.Y.Z
```

token 全程在 shell 变量 `${TOKEN}` 里, 不进入对话/历史明文。

## 坑: pushInsteadOf 反向配置
仓库 `.git/config` 若残留:
```
[url "https://github.com/"]
	pushInsteadOf = https://ghproxy.net/https://github.com/
```
会把 push 强制转回 github.com → 被墙。移除:
```bash
git config --unset url."https://github.com/".pushInsteadOf
git remote -v   # 确认 fetch/push 都走 ghproxy.net
```

## 验证 push 成功
```bash
git ls-remote origin HEAD            # 返回最新 commit SHA = 推送成功
git ls-remote origin refs/tags/vX.Y.Z
git fetch origin main -q && git log origin/main..HEAD --oneline  # 空 = 本地已完全同步
```

## 相关
- hermes-agent 仓库的绕过方式: `.git/config` 里 `[url "https://ghfast.top/https://github.com/"] insteadOf = https://github.com/` (fetch+push 都走镜像)。
- lerobot 仓库 remote url 直接就是 `https://ghfast.top/https://github.com/MikeBMW/lerobot-smolvla-lew.git`, 无需 insteadOf。
